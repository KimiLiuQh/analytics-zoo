#
# Copyright 2018 Analytics Zoo Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from zoo.chronos.model.anomaly.abstract import AnomalyDetector
from zoo.chronos.model.anomaly.util import roll_arr, scale_arr
import numpy as np


def create_tf_model(compress_rate, input_dim, optimizer='adadelta', loss='binary_crossentropy'):
    from tensorflow.keras.layers import Input, Dense
    from tensorflow.keras.models import Model

    inp = Input(shape=(input_dim,))
    encoded = Dense(int(compress_rate * input_dim), activation='relu')(inp)
    decoded = Dense(input_dim, activation='sigmoid')(encoded)
    autoencoder = Model(inp, decoded)
    autoencoder.compile(optimizer=optimizer, loss=loss)
    return autoencoder


class AEDetector(AnomalyDetector):
    """
    Anomaly Detector based on AutoEncoder
    """

    def __init__(self,
                 roll_len=24,
                 ratio=0.1,
                 compress_rate=0.8,
                 batch_size=100,
                 epochs=200,
                 verbose=0,
                 sub_scalef=1):
        """
        Initialize an AE Anomaly Detector.
        AE Anomaly Detector supports two modes to detect anomalies in input time series.
            1. It trains an autoencoder network directly on the input times series and
                calculate anomaly scores based on reconstruction error. For each sample
                in the input, the larger the reconstruction error, the higher the
                anomaly score.
            2. It will first roll the input series into a batch of subsequences, each
                with a fixed length (`roll_len`). Then it trains an autoencoder network on
                the batch of subsequences and calculate the reconstruction error. In
                this mode, both the difference of each point in the rolled samples and
                the subsequence vector are taken into account when calculating the
                anomaly scores. The final score is an aggregation of the two. You may
                use `sub_scalef` to control the weights of subsequence errors.
        :param roll_len: roll_len the length to roll the input data. Usually we set a length
            that is probably a full or half a cycle. e.g. half a day, one day, etc. Note that
            roll_len must be smaller than the length of the input time series
        :param ratio: ratio of anomalies
        :param compress_rate: the compression rate of the autoencoder, changing this value will have
            impact on the reconstruction error it calculated.
        :param batch_size: batch size for autoencoder training
        :param epochs: num of epochs fro autoencoder training
        :param verbose: verbose option for autoencoder training
        :param sub_scalef: scale factor for the subsequence distance when calculating anomaly score
        """
        self.ratio = ratio
        self.compress_rate = compress_rate
        self.roll_len = roll_len
        self.batch_size = batch_size
        self.epochs = epochs
        self.verbose = verbose
        self.sub_scalef = sub_scalef
        self.recon_err = None
        self.recon_err_subseq = None
        self.ad_score = None

    def check_rolled(self, arr):
        if __name__ == '__main__':
            if arr.size == 0:
                raise ValueError("rolled array is empty, ",
                                 "please check if roll_len is larger than the total series length")

    def check_data(self, arr):
        if len(arr.shape) > 1:
            raise ValueError("Only univariate time series is supported")

    def fit(self, y):
        """
        fit the AutoEncoder model to the data
        :param y: the input time series
        :return
        """
        self.check_data(y)
        self.ad_score = np.zeros_like(y)

        if self.roll_len != 0:
            # roll the time series to create sub sequences
            y = roll_arr(y, self.roll_len)
            self.check_rolled(y)

        y = scale_arr(y)

        # TODO add pytorch model
        ae_model = create_tf_model(self.compress_rate, len(y[0]))
        ae_model.fit(y,
                     y,
                     batch_size=self.batch_size,
                     epochs=self.epochs,
                     verbose=self.verbose)
        y_pred = ae_model.predict(y)

        # calculate the recon err for each data point in rolled array
        self.recon_err = abs(y - y_pred)
        # calculate the (aggregated) recon err for each sub sequence
        if self.roll_len != 0:
            self.recon_err_subseq = np.linalg.norm(self.recon_err, axis=1)

    def score(self):
        """
        gets the anomaly scores for each sample.
        All anomaly scores are positive.
        If rolled , the anomaly score is calculated by aggregating the reconstruction
        errors of each point and subsequence.
        :return: the anomaly scores, in an array format with the same size as input
        """
        if self.ad_score is None:
            raise ValueError("please call fit before calling score")

        # if input is rolled
        if self.recon_err_subseq is not None:
            # recon_err = MinMaxScaler().fit_transform(self.recon_err)
            # recon_err_subseq = MinMaxscaler().fit_transform(self.recon_err_subseq.reshape(-1, 1))
            for index, e in np.ndenumerate(self.recon_err):
                agg_err = e + self.sub_scalef * self.recon_err_subseq[index[0]]
                y_index = index[0] + index[1]
                # only keep the largest err score for each ts sample
                if agg_err > self.ad_score[y_index]:
                    self.ad_score[y_index] = agg_err
        else:
            self.ad_score = self.recon_err

        self.ad_score = scale_arr(self.ad_score.reshape(-1, 1)).squeeze()

        return self.ad_score

    def anomaly_indexes(self):
        """
        gets the indexes of N samples with the largest anomaly scores in y
        (N = size of input y * AEDetector.ratio)
        :return: the indexes of N samples
        """
        if self.ad_score is None:
            self.score()
        num_anomalies = int(len(self.ad_score) * self.ratio)
        return self.ad_score.argsort()[-num_anomalies:]