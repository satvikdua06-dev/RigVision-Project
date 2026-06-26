"""
BoT-SORT matching utilities.

Based on: https://github.com/NirAharon/BoT-SORT/blob/main/tracker/matching.py

Changes from upstream:
  - Relative imports (from . import kalman_filter) for RigVision package structure
  - Replaced cython_bbox with pure-numpy IoU (avoids C compilation on Windows)
  - Replaced deprecated np.float with np.float64
  - Added lap fallback to scipy.optimize.linear_sum_assignment
"""

import numpy as np
import scipy
from scipy.spatial.distance import cdist

from . import kalman_filter

# Try lap (fast Jonker-Volgenant solver), fall back to scipy
try:
    import lap
    _USE_LAP = True
except ImportError:
    from scipy.optimize import linear_sum_assignment as scipy_lsa
    _USE_LAP = False


def merge_matches(m1, m2, shape):
    O, P, Q = shape
    m1 = np.asarray(m1)
    m2 = np.asarray(m2)

    M1 = scipy.sparse.coo_matrix((np.ones(len(m1)), (m1[:, 0], m1[:, 1])), shape=(O, P))
    M2 = scipy.sparse.coo_matrix((np.ones(len(m2)), (m2[:, 0], m2[:, 1])), shape=(P, Q))

    mask = M1 * M2
    match = mask.nonzero()
    match = list(zip(match[0], match[1]))
    unmatched_O = tuple(set(range(O)) - set([i for i, j in match]))
    unmatched_Q = tuple(set(range(Q)) - set([j for i, j in match]))

    return match, unmatched_O, unmatched_Q


def linear_assignment(cost_matrix, thresh):
    """Solve the linear assignment problem.

    Uses lap (Jonker-Volgenant) if available, otherwise falls back to
    scipy.optimize.linear_sum_assignment (Hungarian).
    """
    if cost_matrix.size == 0:
        return (
            np.empty((0, 2), dtype=int),
            tuple(range(cost_matrix.shape[0])),
            tuple(range(cost_matrix.shape[1])),
        )

    if _USE_LAP:
        _, x, y = lap.lapjv(cost_matrix, extend_cost=True, cost_limit=thresh)
        matches = [[ix, mx] for ix, mx in enumerate(x) if mx >= 0]
        unmatched_a = np.where(x < 0)[0]
        unmatched_b = np.where(y < 0)[0]
        matches = np.asarray(matches) if matches else np.empty((0, 2), dtype=int)
    else:
        # Scipy fallback
        row_idx, col_idx = scipy_lsa(cost_matrix)
        matches = []
        unmatched_a_set = set(range(cost_matrix.shape[0]))
        unmatched_b_set = set(range(cost_matrix.shape[1]))
        for r, c in zip(row_idx, col_idx):
            if cost_matrix[r, c] <= thresh:
                matches.append([r, c])
                unmatched_a_set.discard(r)
                unmatched_b_set.discard(c)
        matches = np.asarray(matches) if matches else np.empty((0, 2), dtype=int)
        unmatched_a = np.array(sorted(unmatched_a_set))
        unmatched_b = np.array(sorted(unmatched_b_set))

    return matches, unmatched_a, unmatched_b


def _bbox_ious_numpy(atlbrs, btlbrs):
    """Compute IoU between two sets of bounding boxes (pure numpy).

    Replaces cython_bbox.bbox_overlaps — same result, no C compilation.

    Args:
        atlbrs: np.ndarray of shape (N, 4) in [x1, y1, x2, y2] format
        btlbrs: np.ndarray of shape (M, 4) in [x1, y1, x2, y2] format

    Returns:
        np.ndarray of shape (N, M) with IoU values.
    """
    a = np.ascontiguousarray(atlbrs, dtype=np.float64)
    b = np.ascontiguousarray(btlbrs, dtype=np.float64)

    N = a.shape[0]
    M = b.shape[0]
    ious = np.zeros((N, M), dtype=np.float64)

    if N == 0 or M == 0:
        return ious

    # Intersection
    # a[:, None, :2]  shape (N, 1, 2) — top-left coords of a
    # b[None, :, :2]  shape (1, M, 2) — top-left coords of b
    inter_tl = np.maximum(a[:, None, :2], b[None, :, :2])  # (N, M, 2)
    inter_br = np.minimum(a[:, None, 2:], b[None, :, 2:])  # (N, M, 2)
    inter_wh = np.clip(inter_br - inter_tl, 0, None)       # (N, M, 2)
    inter_area = inter_wh[:, :, 0] * inter_wh[:, :, 1]     # (N, M)

    # Areas
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])     # (N,)
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])     # (M,)

    # Union
    union = area_a[:, None] + area_b[None, :] - inter_area  # (N, M)

    # IoU
    ious = np.where(union > 0, inter_area / union, 0.0)

    return ious


def ious(atlbrs, btlbrs):
    """Compute IoU between two sets of bounding boxes.

    :type atlbrs: list[tlbr] | np.ndarray
    :type btlbrs: list[tlbr] | np.ndarray
    :rtype: np.ndarray
    """
    ious_out = np.zeros((len(atlbrs), len(btlbrs)), dtype=np.float64)
    if ious_out.size == 0:
        return ious_out

    ious_out = _bbox_ious_numpy(
        np.ascontiguousarray(atlbrs, dtype=np.float64),
        np.ascontiguousarray(btlbrs, dtype=np.float64),
    )
    return ious_out


def tlbr_expand(tlbr, scale=1.2):
    w = tlbr[2] - tlbr[0]
    h = tlbr[3] - tlbr[1]

    half_scale = 0.5 * scale

    tlbr[0] -= half_scale * w
    tlbr[1] -= half_scale * h
    tlbr[2] += half_scale * w
    tlbr[3] += half_scale * h

    return tlbr


def iou_distance(atracks, btracks):
    """Compute cost based on IoU.

    :type atracks: list[STrack]
    :type btracks: list[STrack]
    :rtype cost_matrix: np.ndarray
    """
    if (len(atracks) > 0 and isinstance(atracks[0], np.ndarray)) or (
        len(btracks) > 0 and isinstance(btracks[0], np.ndarray)
    ):
        atlbrs = atracks
        btlbrs = btracks
    else:
        atlbrs = [track.tlbr for track in atracks]
        btlbrs = [track.tlbr for track in btracks]
    _ious = ious(atlbrs, btlbrs)
    cost_matrix = 1 - _ious

    return cost_matrix


def v_iou_distance(atracks, btracks):
    """Compute cost based on IoU using predicted bboxes.

    :type atracks: list[STrack]
    :type btracks: list[STrack]
    :rtype cost_matrix: np.ndarray
    """
    if (len(atracks) > 0 and isinstance(atracks[0], np.ndarray)) or (
        len(btracks) > 0 and isinstance(btracks[0], np.ndarray)
    ):
        atlbrs = atracks
        btlbrs = btracks
    else:
        atlbrs = [track.tlwh_to_tlbr(track.pred_bbox) for track in atracks]
        btlbrs = [track.tlwh_to_tlbr(track.pred_bbox) for track in btracks]
    _ious = ious(atlbrs, btlbrs)
    cost_matrix = 1 - _ious

    return cost_matrix


def embedding_distance(tracks, detections, metric='cosine'):
    """Compute cost based on appearance embeddings.

    :param tracks: list[STrack]
    :param detections: list[BaseTrack]
    :param metric: distance metric
    :return: cost_matrix np.ndarray
    """
    cost_matrix = np.zeros((len(tracks), len(detections)), dtype=np.float64)
    if cost_matrix.size == 0:
        return cost_matrix
    det_features = np.asarray([track.curr_feat for track in detections], dtype=np.float64)
    track_features = np.asarray([track.smooth_feat for track in tracks], dtype=np.float64)

    cost_matrix = np.maximum(0.0, cdist(track_features, det_features, metric))
    return cost_matrix


def gate_cost_matrix(kf, cost_matrix, tracks, detections, only_position=False):
    if cost_matrix.size == 0:
        return cost_matrix
    gating_dim = 2 if only_position else 4
    gating_threshold = kalman_filter.chi2inv95[gating_dim]
    measurements = np.asarray([det.to_xywh() for det in detections])
    for row, track in enumerate(tracks):
        gating_distance = kf.gating_distance(
            track.mean, track.covariance, measurements, only_position
        )
        cost_matrix[row, gating_distance > gating_threshold] = np.inf
    return cost_matrix


def fuse_motion(kf, cost_matrix, tracks, detections, only_position=False, lambda_=0.98):
    if cost_matrix.size == 0:
        return cost_matrix
    gating_dim = 2 if only_position else 4
    gating_threshold = kalman_filter.chi2inv95[gating_dim]
    measurements = np.asarray([det.to_xywh() for det in detections])
    for row, track in enumerate(tracks):
        gating_distance = kf.gating_distance(
            track.mean, track.covariance, measurements, only_position, metric='maha'
        )
        cost_matrix[row, gating_distance > gating_threshold] = np.inf
        cost_matrix[row] = lambda_ * cost_matrix[row] + (1 - lambda_) * gating_distance
    return cost_matrix


def fuse_iou(cost_matrix, tracks, detections):
    if cost_matrix.size == 0:
        return cost_matrix
    reid_sim = 1 - cost_matrix
    iou_dist = iou_distance(tracks, detections)
    iou_sim = 1 - iou_dist
    fuse_sim = reid_sim * (1 + iou_sim) / 2
    fuse_cost = 1 - fuse_sim
    return fuse_cost


def fuse_score(cost_matrix, detections):
    if cost_matrix.size == 0:
        return cost_matrix
    iou_sim = 1 - cost_matrix
    det_scores = np.array([det.score for det in detections])
    det_scores = np.expand_dims(det_scores, axis=0).repeat(cost_matrix.shape[0], axis=0)
    fuse_sim = iou_sim * det_scores
    fuse_cost = 1 - fuse_sim
    return fuse_cost