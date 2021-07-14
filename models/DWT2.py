import math
import pywt
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from tensorflow.keras.datasets import mnist, cifar10


class DWT(layers.Layer):
    def __init__(self, name='haar', **kwargs):
        super(DWT, self).__init__(**kwargs)
        self._name = self.name + "_" + name
        # get filter coeffs from 3rd party lib
        wavelet = pywt.Wavelet(name)
        self.dec_len = wavelet.dec_len

        # decomposition filter low pass and hight pass coeffs
        db2_lpf = wavelet.dec_lo
        db2_hpf = wavelet.dec_hi

        # covert values into tensor and reshape for convolution math
        db2_lpf = tf.constant(db2_lpf)
        self.db2_lpf = tf.reshape(db2_lpf, (1, wavelet.dec_len, 1, 1))

        db2_hpf = tf.constant(db2_hpf)
        self.db2_hpf = tf.reshape(db2_hpf, (1, wavelet.dec_len, 1, 1))

        self.conv_type = "VALID"
        self.border_padd = "SYMMETRIC"

    def build(self, input_shape):
        # filter dims should be bigger if input is not gray scale
        if input_shape[-1] != 1:
            self.db2_lpf = tf.repeat(self.db2_lpf, input_shape[-1], axis=-1)
            self.db2_hpf = tf.repeat(self.db2_hpf, input_shape[-1], axis=-1)

    def call(self, inputs, training=None, mask=None):

        # border padding symatric add coulums
        inputs_pad = tf.pad(inputs, [[0, 0], [0, 0], [self.dec_len-1, self.dec_len-1], [0, 0]], self.border_padd)

        # approximation conv only rows
        a = tf.nn.conv2d(
            inputs_pad, self.db2_lpf, padding=self.conv_type, strides=[1, 1, 1, 1],
        )
        # details conv only rows
        d = tf.nn.conv2d(
            inputs_pad, self.db2_hpf, padding=self.conv_type, strides=[1, 1, 1, 1],
        )
        # ds - downsample
        a_ds = a[:, :, 1:a.shape[2]:2, :]
        d_ds = d[:, :, 1:a.shape[2]:2, :]

        # border padding symatric add rows
        a_ds_pad = tf.pad(a_ds, [[0, 0], [self.dec_len-1, self.dec_len-1], [0, 0], [0, 0]], self.border_padd)
        d_ds_pad = tf.pad(d_ds, [[0, 0], [self.dec_len-1, self.dec_len-1], [0, 0], [0, 0]], self.border_padd)

        # convolution is done on the rows so we need to
        # transpose the matrix in order to convolve the colums
        a_ds_pad = tf.transpose(a_ds_pad, perm=[0, 2, 1, 3])
        d_ds_pad = tf.transpose(d_ds_pad, perm=[0, 2, 1, 3])

        # aa approximation approximation
        aa = tf.nn.conv2d(
            a_ds_pad, self.db2_lpf, padding=self.conv_type, strides=[1, 1, 1, 1],
        )
        # ad approximation details
        ad = tf.nn.conv2d(
            a_ds_pad, self.db2_hpf, padding=self.conv_type, strides=[1, 1, 1, 1],
        )
        # ad details aproximation
        da = tf.nn.conv2d(
            d_ds_pad, self.db2_lpf, padding=self.conv_type, strides=[1, 1, 1, 1],
        )
        # dd details details
        dd = tf.nn.conv2d(
            d_ds_pad, self.db2_hpf, padding=self.conv_type, strides=[1, 1, 1, 1],
        )

        # transpose back the matrix
        aa = tf.transpose(aa, perm=[0, 2, 1, 3])
        ad = tf.transpose(ad, perm=[0, 2, 1, 3])
        da = tf.transpose(da, perm=[0, 2, 1, 3])
        dd = tf.transpose(dd, perm=[0, 2, 1, 3])

        # down sample
        ll = aa[:, 1:aa.shape[1]:2, :, :]
        lh = ad[:, 1:aa.shape[1]:2, :, :]
        hl = da[:, 1:aa.shape[1]:2, :, :]
        hh = dd[:, 1:aa.shape[1]:2, :, :]

        # concate all outputs ionto tensor
        x = tf.concat([ll, lh, hl, hh], axis=-1)

        return x


class IDWT(layers.Layer):
    def __init__(self):
        super(IDWT, self).__init__()

        self.pad_type = "VALID"
        # calculate Decomposition LPF and HPF
        db2_h0 = (1+math.sqrt(3))/(4*math.sqrt(2))
        db2_h1 = (3+math.sqrt(3))/(4*math.sqrt(2))
        db2_h2 = (3-math.sqrt(3))/(4*math.sqrt(2))
        db2_h3 = (1-math.sqrt(3))/(4*math.sqrt(2))

        db2_lpf_r = [db2_h3, db2_h2, db2_h1, db2_h0]
        db2_hpf_r = [-db2_h0, db2_h1, -db2_h2, db2_h3]

        db2_lpf = tf.constant(db2_lpf_r)
        self.db2_lpf = tf.reshape(db2_lpf, (1, 4, 1, 1))

        db2_hpf = tf.constant(db2_hpf_r)
        self.db2_hpf = tf.reshape(db2_hpf, (1, 4, 1, 1))

    def upsampler2d(self, x):
        # zero_tensor = tf.zeros(shape=x.shape, dtype=tf.float32)
        zero_tensor = tf.zeros_like(x, dtype=tf.float32)
        stack_rows = tf.stack([x, zero_tensor], axis=3)
        stack_rows = tf.reshape(stack_rows, shape=[-1, x.shape[1], x.shape[2]*2, x.shape[3]])
        stack_rows = tf.transpose(stack_rows, perm=[0, 2, 1, 3])
        # zero_tensor_1 = tf.zeros(shape=stack_rows.shape, dtype=tf.float32)
        zero_tensor_1 = tf.zeros_like(stack_rows, dtype=tf.float32)
        stack_rows_cols = tf.stack([stack_rows, zero_tensor_1], axis=3)
        us_padded = tf.reshape(stack_rows_cols, shape=[-1, x.shape[1]*2, x.shape[2]*2, x.shape[3]])
        us_padded = tf.transpose(us_padded, perm=[0, 2, 1, 3])
        return us_padded

    def call(self, inputs, training=None, mask=None):
        x = tf.pad(inputs, [[0, 0], [3, 3], [3, 3], [0, 0]], "SYMMETRIC")
        x = tf.cast(x, tf.float32)

        ll = tf.expand_dims(x[:, :, :, 0], axis=-1)
        lh = tf.expand_dims(x[:, :, :, 1], axis=-1)
        hl = tf.expand_dims(x[:, :, :, 2], axis=-1)
        hh = tf.expand_dims(x[:, :, :, 3], axis=-1)

        ll_us_pad = self.upsampler2d(ll)
        lh_us_pad = self.upsampler2d(lh)
        hl_us_pad = self.upsampler2d(hl)
        hh_us_pad = self.upsampler2d(hh)

        ll_conv_lpf = tf.nn.conv2d(ll_us_pad, self.db2_lpf, padding=self.pad_type, strides=[1, 1, 1, 1], )
        ll_conv_lpf_tr = tf.transpose(ll_conv_lpf, perm=[0, 2, 1, 3])
        ll_conv_lpf_lpf = tf.nn.conv2d(ll_conv_lpf_tr, self.db2_lpf, padding=self.pad_type, strides=[1, 1, 1, 1], )
        ll_conv_lpf_lpf_tr = tf.transpose(ll_conv_lpf_lpf, perm=[0, 2, 1, 3])

        lh_conv_lpf = tf.nn.conv2d(lh_us_pad, self.db2_lpf, padding=self.pad_type, strides=[1, 1, 1, 1], )
        lh_conv_lpf_tr = tf.transpose(lh_conv_lpf, perm=[0, 2, 1, 3])
        lh_conv_lpf_hpf = tf.nn.conv2d(lh_conv_lpf_tr, self.db2_lpf, padding=self.pad_type, strides=[1, 1, 1, 1], )
        lh_conv_lpf_hpf_tr = tf.transpose(lh_conv_lpf_hpf, perm=[0, 2, 1, 3])

        hl_conv_hpf = tf.nn.conv2d(hl_us_pad, self.db2_hpf, padding=self.pad_type, strides=[1, 1, 1, 1], )
        hl_conv_hpf_tr = tf.transpose(hl_conv_hpf, perm=[0, 2, 1, 3])
        hl_conv_hpf_lpf = tf.nn.conv2d(hl_conv_hpf_tr, self.db2_lpf, padding=self.pad_type, strides=[1, 1, 1, 1], )
        hl_conv_hpf_lpf_tr = tf.transpose(hl_conv_hpf_lpf, perm=[0, 2, 1, 3])

        HH_conv_hpf = tf.nn.conv2d(hh_us_pad, self.db2_hpf, padding=self.pad_type, strides=[1, 1, 1, 1], )
        HH_conv_hpf_tr = tf.transpose(HH_conv_hpf, perm=[0, 2, 1, 3])
        HH_conv_hpf_hpf = tf.nn.conv2d(HH_conv_hpf_tr, self.db2_hpf, padding=self.pad_type, strides=[1, 1, 1, 1], )
        HH_conv_hpf_hpf_tr = tf.transpose(HH_conv_hpf_hpf, perm=[0, 2, 1, 3])

        LL_LH = tf.math.add(ll_conv_lpf_lpf_tr, lh_conv_lpf_hpf_tr)
        HL_HH = tf.math.add(hl_conv_hpf_lpf_tr, HH_conv_hpf_hpf_tr)

        reconstructed = tf.math.add(LL_LH, HL_HH)
        return reconstructed[:, 5:-4, 5:-4, :]


if __name__ == "__main__":
    # (x_train, y_train), (x_test, y_test) = cifar10.load_data()
    # x_train = x_train.astype("float32")
    # x_test = x_test.astype("float32")
    # # x_train = cv2.imread("../input/LennaGrey.png", 0)
    # frog = tf.expand_dims(
    #     x_train[0, :, :, :], 0, name=None
    # )
    # print("frog shape", frog.shape)
    model = keras.Sequential()
    model.add(keras.Input(shape=(256, 256, 4)))
    model.add(IDWT())
    model.summary()



    # a = model.predict(frog, steps=1)
    # #
    # approx = tf.image.convert_image_dtype(a[0, ..., 0], dtype=tf.float32)
    # with tf.Session() as sess:
    #     img = sess.run(approx)
    # #     pass
    # #
    # img = np.clip(img, 0, 255)
    # img = np.ceil(img)
    # img = img.astype("uint8")
    # with open(r"D:\TEMP\LL_python_layer.raw", "wb") as outfile:
    #     outfile.write(img)  # Write it

    # model = models.WaveletCifar10CNN.WaveletCNN((32,32,3), 10)
    # model.summary()