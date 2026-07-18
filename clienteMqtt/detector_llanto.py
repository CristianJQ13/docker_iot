import numpy as np
import librosa
import tensorflow as tf
from scipy.signal import resample

MODEL_PATH = "detector_llanto.keras"

SR = 16000
DURATION = 3.0
TARGET_LEN = int(SR * DURATION)

N_MFCC = 40
MAX_LEN = int(SR * DURATION / 512) + 1

modelo = tf.keras.models.load_model(MODEL_PATH)

def detectar_llanto(audio_bytes):

    audio = np.frombuffer(audio_bytes, dtype=np.uint8).astype(np.float32)

    audio = (audio - 128.0) / 128.0

    audio = resample(audio, TARGET_LEN)

    mfcc = librosa.feature.mfcc(
        y=audio,
        sr=SR,
        n_mfcc=N_MFCC
    )

    mfcc = (mfcc - np.mean(mfcc)) / (np.std(mfcc) + 1e-8)

    if mfcc.shape[1] < MAX_LEN:

        pad = MAX_LEN - mfcc.shape[1]

        mfcc = np.pad(
            mfcc,
            ((0,0),(0,pad)),
            mode="constant"
        )

    else:

        mfcc = mfcc[:, :MAX_LEN]

    mfcc = mfcc.reshape(1,N_MFCC,MAX_LEN,1)

    prob = modelo.predict(mfcc, verbose=0)[0][0]

    return float(prob)