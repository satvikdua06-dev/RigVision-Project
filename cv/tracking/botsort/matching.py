import numpy as np
import scipy
from scipy.spatial.distance import cdist
from . import kalman_filter

try:
    import lap
    _USE_LAP = True
except ImportError:
    from scipy.optimize import linear_sum_assignment as scipy_lsa
    _USE_LAP = False

def merge_matches(m1, m2, shape):
    O, P, Q = shape
    m1, m2 = np.asarray(m1), np.asarray(m2)
    M1 = scipy.sparse.coo_matrix((np.ones(len(m1)), (m1[:, 0], m1[:, 1])), shape=(O, P))
    M2 = scipy.sparse.coo_matrix((np.ones(len(m2)), (m2[:, 0], m2[:, 1])), shape=(P, Q))
    mask = M1 * M2
    match = list(zip(*mask.nonzero()))
    unmatched_O = tuple(set(range(O)) - {i for i, j in match})
    unmatched_Q = tuple(set(range(Q)) - {j for i, j in match})
    return match, unmatched_O, unmatched_Q

def linear_assignment(cost_matrix, thresh):
    if cost_matrix.size == 0:
        return np.empty((0, 2), dtype=int), tuple(range(cost_matrix.shape[0])), tuple(range(cost_matrix.shape[1]))
    if _USE_LAP:
        _, x, y = lap.lapjv(cost_matrix, extend_cost=True, cost_limit=thresh)
        matches = np.asarray([[ix, mx] for ix, mx in enumerate(x) if mx >= 0]) if any(mx >= 0 for mx in x) else np.empty((0, 2), dtype=int)
        return matches, np.where(x < 0)[0], np.where(y < 0)[0]
    row_idx, col_idx = scipy_lsa(cost_matrix)
    matches, u_a, u_b = [], set(range(cost_matrix.shape[0])), set(range(cost_matrix.shape[1]))
    for r, c in zip(row_idx, col_idx):
        if cost_matrix[r, c] <= thresh:
            matches.append([r, c])
            u_a.discard(r)
            u_b.discard(c)
    return np.asarray(matches) if matches else np.empty((0, 2), dtype=int), np.array(sorted(u_a)), np.array(sorted(u_b))

def _bbox_ious_numpy(a, b):
    a = np.ascontiguousarray(a, dtype=np.float64)
    b = np.ascontiguousarray(b, dtype=np.float64)
    if a.shape[0] == 0 or b.shape[0] == 0:
        return np.zeros((a.shape[0], b.shape[0]), dtype=np.float64)
    inter_tl = np.maximum(a[:, None, :2], b[None, :, :2])
    inter_br = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter_wh = np.clip(inter_br - inter_tl, 0, None)
    inter_area = inter_wh[:, :, 0] * inter_wh[:, :, 1]
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter_area
    return np.where(union > 0, inter_area / union, 0.0)

def ious(atlbrs, btlbrs):
    if len(atlbrs) == 0 or len(btlbrs) == 0:
        return np.zeros((len(atlbrs), len(btlbrs)), dtype=np.float64)
    return _bbox_ious_numpy(atlbrs, btlbrs)

def tlbr_expand(tlbr, scale=1.2):
    w, h = tlbr[2] - tlbr[0], tlbr[3] - tlbr[1]
    hs = 0.5 * scale
    tlbr[0] -= hs * w
    tlbr[1] -= hs * h
    tlbr[2] += hs * w
    tlbr[3] += hs * h
    return tlbr

def iou_distance(atracks, btracks):
    if len(atracks) > 0 and isinstance(atracks[0], np.ndarray):
        return 1 - ious(atracks, btracks)
    return 1 - ious([t.tlbr for t in atracks], [t.tlbr for t in btracks])

def v_iou_distance(atracks, btracks):
    if len(atracks) > 0 and isinstance(atracks[0], np.ndarray):
        return 1 - ious(atracks, btracks)
    return 1 - ious([t.tlwh_to_tlbr(t.pred_bbox) for t in atracks], [t.tlwh_to_tlbr(t.pred_bbox) for t in btracks])

def embedding_distance(tracks, detections, metric='cosine'):
    if len(tracks) == 0 or len(detections) == 0:
        return np.zeros((len(tracks), len(detections)), dtype=np.float64)
    det_f = np.asarray([t.curr_feat for t in detections], dtype=np.float64)
    trk_f = np.asarray([t.smooth_feat for t in tracks], dtype=np.float64)
    return np.maximum(0.0, cdist(trk_f, det_f, metric))

def gate_cost_matrix(kf, cost_matrix, tracks, detections, only_position=False):
    if cost_matrix.size == 0: return cost_matrix
    limit = kalman_filter.chi2inv95[2 if only_position else 4]
    meas = np.asarray([d.to_xywh() for d in detections])
    for r, t in enumerate(tracks):
        dist = kf.gating_distance(t.mean, t.covariance, meas, only_position)
        cost_matrix[r, dist > limit] = np.inf
    return cost_matrix

def fuse_motion(kf, cost_matrix, tracks, detections, only_position=False, lambda_=0.98):
    if cost_matrix.size == 0: return cost_matrix
    limit = kalman_filter.chi2inv95[2 if only_position else 4]
    meas = np.asarray([d.to_xywh() for d in detections])
    for r, t in enumerate(tracks):
        dist = kf.gating_distance(t.mean, t.covariance, meas, only_position, metric='maha')
        cost_matrix[r, dist > limit] = np.inf
        cost_matrix[r] = lambda_ * cost_matrix[r] + (1 - lambda_) * dist
    return cost_matrix

def fuse_iou(cost_matrix, tracks, detections):
    if cost_matrix.size == 0: return cost_matrix
    return 1 - (1 - cost_matrix) * (1 + (1 - iou_distance(tracks, detections))) / 2

def fuse_score(cost_matrix, detections):
    if cost_matrix.size == 0: return cost_matrix
    scores = np.array([d.score for d in detections])
    return 1 - (1 - cost_matrix) * np.expand_dims(scores, axis=0)