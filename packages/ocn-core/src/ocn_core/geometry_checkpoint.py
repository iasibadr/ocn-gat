"""Explicit trusted-host checkpoints for GeometryLearner, with a coordinate contract.

No writer locking or anti-rollback authority. Callers serialize writers and bind
the contract to their units, scales, coordinate order and observation semantics.
"""
import json
import os
from pathlib import Path
import stat
import tempfile
import numpy as np
from .geometry_learning import GeometryLearner
from .experience_memory import label
from .model_budget import sync_directory

LIMIT = 262144
FIELDS = {'format','contract_id','units','learning_rate','score_rate','observations',
          'parameters','scores','pending_coordinates'}


def _restore(value, contract_id):
    label(contract_id)
    if (type(value) is not dict or set(value) != FIELDS or
            value['format'] != 'gat.geometry.v1' or value['contract_id'] != contract_id):
        raise ValueError('Geometry checkpoint contract mismatch')
    learner = GeometryLearner(value['units'], learning_rate=value['learning_rate'],
                              score_rate=value['score_rate'])
    if type(value['observations']) is not int or not 0 <= value['observations'] < 2**63:
        raise ValueError('Invalid observation count')
    parameters = value['parameters']
    if type(parameters) is not list or len(parameters) != 3:
        raise ValueError('Three parameter arrays required')
    restored = []
    for index, raw in enumerate(parameters):
        array = np.asarray(raw)
        shape = (learner.units,4,4) if index == 2 else (learner.units,4)
        if array.shape != shape or array.dtype.kind not in 'fiu':
            raise ValueError('Invalid parameter shape or type')
        array = array.astype(float, copy=True)
        axes = (1,2) if index == 2 else 1
        bound = 2. if index == 0 else 4.
        if not np.isfinite(array).all() or np.any(np.linalg.norm(array,axis=axes) > bound+1e-12):
            raise ValueError('Parameter norm outside learner bounds')
        restored.append(array)
    scores = np.asarray(value['scores'])
    if scores.shape != (3,) or scores.dtype.kind not in 'fiu':
        raise ValueError('Invalid score vector')
    scores = scores.astype(float, copy=True)
    if not np.isfinite(scores).all() or np.any(scores<0) or np.any(scores>4):
        raise ValueError('Scores outside bounded MSE range')
    learner._parameters = restored
    learner._scores = scores
    learner.observations = value['observations']
    if value['pending_coordinates'] is not None:
        learner.predict(value['pending_coordinates'])
    return learner


def save_geometry(learner, path, *, contract_id):
    if not isinstance(learner, GeometryLearner):
        raise ValueError('GeometryLearner required')
    value = dict(format='gat.geometry.v1', contract_id=contract_id, units=learner.units,
        learning_rate=learner.learning_rate, score_rate=learner.score_rate,
        observations=learner.observations, parameters=[p.tolist() for p in learner._parameters],
        scores=learner._scores.tolist(),
        pending_coordinates=None if learner._pending is None else learner._pending[0].tolist())
    _restore(value, contract_id)
    raw = json.dumps(value, allow_nan=False, sort_keys=True).encode()
    if len(raw) > LIMIT:
        raise ValueError('Checkpoint too large')
    path = Path(path).absolute()
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('Regular checkpoint destination required')
    fd, temporary = tempfile.mkstemp(prefix='.geometry-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def load_geometry(path, *, contract_id):
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('Regular checkpoint file required')
        raw = handle.read(LIMIT+1)
    if len(raw) > LIMIT:
        raise ValueError('Checkpoint too large')
    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):raise ValueError('Duplicate checkpoint fields')
        return value
    return _restore(json.loads(raw, object_pairs_hook=unique), contract_id)
