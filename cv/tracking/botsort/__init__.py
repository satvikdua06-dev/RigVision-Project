"""
BoT-SORT tracking package for RigVision-3D.

Provides the BoTSORT multi-object tracker with Kalman filtering,
IoU + ReID appearance matching, and camera motion compensation.
"""

from .bot_sort import BoTSORT, STrack
from .basetrack import BaseTrack, TrackState
from .kalman_filter import KalmanFilter

__all__ = ["BoTSORT", "STrack", "BaseTrack", "TrackState", "KalmanFilter"]
