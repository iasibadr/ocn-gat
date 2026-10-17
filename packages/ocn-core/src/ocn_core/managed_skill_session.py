"""Opt-in maintenance of procedural memory, with permissions kept separate.

The budget is canonical serialized retained-state bytes, NOT process RSS. Callback
state, model weights, external source files and transient copies are excluded.
Maintenance is explicit between requests; this is not an automatic hard RAM cap.
Host calibration cannot be evicted. A target below protected state is reported as
unmet, never as a successful reduction. Retired records are not recoverable here.
"""
from dataclasses import asdict
import json
from threading import Lock

from .skill_session import SkillSession


def size(value):
    return len(json.dumps(value,sort_keys=True,separators=(',',':'),
                          ensure_ascii=False,allow_nan=False).encode('utf-8'))


class ManagedSkillSession(SkillSession):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._last_used={}
        self._operation_lock=Lock()

    def _state(self):
        return dict(
            permissions=self.permissions,
            calibrations=self.bank.authority,
            pending_examples=self.examples,
            contracts={k:dict(contract=None if v[0] is None else asdict(v[0]),receipt=v[1])
                       for k,v in self.bank.entries.items()},
            audit=dict(bank=self.bank.audit,schema=self.schema_events,retirement=self.retirement_events),
            metadata=dict(last_used=self._last_used,learned=sorted(self.learned_calibrations),
                requests=self.requests,worker_calls=self.worker_calls,
                attempts=self.bank.attempts,hits=self.bank.hits,negative_hits=self.bank.negative_hits,
                evictions=self.bank.evictions))

    def _report(self):
        state=self._state()
        return dict(serialized_bytes=size(state),
            category_bytes={k:size(v) for k,v in state.items()},
            scope='Canonical retained-state JSON; excludes callbacks, source files, model weights and transient/RSS overhead')

    def memory_report(self):
        if not self._operation_lock.acquire(blocking=False):raise RuntimeError('Session busy')
        try:return self._report()
        finally:self._operation_lock.release()

    def run(self,connector,revision,record,identity,**kwargs):
        if not self._operation_lock.acquire(blocking=False):raise RuntimeError('Session busy')
        before=self.requests
        try:return super().run(connector,revision,record,identity,**kwargs)
        finally:
            if self.requests>before:self._last_used[connector]=self.requests
            self._operation_lock.release()

    def permit(self,*args,**kwargs):
        if not self._operation_lock.acquire(blocking=False):raise RuntimeError('Session busy')
        try:return super().permit(*args,**kwargs)
        finally:self._operation_lock.release()

    def authorize(self,*args,**kwargs):
        if not self._operation_lock.acquire(blocking=False):raise RuntimeError('Session busy')
        try:return super().authorize(*args,**kwargs)
        finally:self._operation_lock.release()

    def trim_memory(self,target_bytes,*,protect=()):
        """Retire least recently requested learned scopes, including their examples.

        Explicit host calibration and permissions survive. Pending feedback is
        learned state too. Protection applies to the complete connector scope.
        The receipt belongs to the caller, not an unbounded internal history.
        """
        if type(target_bytes) is not int or target_bytes<0:
            raise ValueError('Nonnegative integer serialized-byte target required')
        if type(protect) not in (tuple,list) or any(type(k) is not str for k in protect):
            raise ValueError('Explicit connector protection list required')
        if not self._operation_lock.acquire(blocking=False):raise RuntimeError('Session busy')
        try:
            if any(k not in self.permissions for k in protect):raise ValueError('Unknown protected connector')
            before=self._report()
            removable=(self.learned_calibrations | set(self.examples))-set(protect)
            # Defensive exclusion: host-authorized calibrations are never learned data.
            removable={k for k in removable if k not in self.bank.authority or k in self.learned_calibrations}
            order=sorted(removable,key=lambda k:(self._last_used.get(k,0),k))
            removed=[]
            for key in order:
                if self._report()['serialized_bytes']<=target_bytes:break
                if not self._retire_learned(key,'memory_pressure'):
                    self.examples.pop(key,None)
                    self.retirement_events.append(dict(connector=key,revision=self.permissions[key],
                        reason='pending_memory_pressure',request=self.requests))
                    self.retirement_events=self.retirement_events[-16:]
                self._last_used.pop(key,None)
                removed.append(key)
            after=self._report()
            return dict(before=before,after=after,target_bytes=target_bytes,
                target_met=after['serialized_bytes']<=target_bytes,retired=removed,
                bytes_released=before['serialized_bytes']-after['serialized_bytes'],
                reason='least_recent_learned_scope',permissions_preserved=True)
        finally:self._operation_lock.release()
