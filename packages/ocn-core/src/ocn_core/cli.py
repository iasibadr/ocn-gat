"""One explicit aggregation request; no daemon or background work."""
import argparse
import json
import sqlite3
from pathlib import Path
from . import (Agent, DNA, DirectoryHabitat, save_checkpoint, load_checkpoint,
               ScheduledAgent, ScheduledDNA, RepackingAgent, RepackingDNA, CompactReservoir, DissipativeHabitat)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('habitat')
    parser.add_argument('--source', action='append', required=True,
                        help='SOURCE=INITIAL_FILENAME; repeat once per source')
    parser.add_argument('--state', help='Checkpoint outside the habitat; one writer only')
    parser.add_argument('--step', type=int, default=0)
    parser.add_argument('--budget', type=int, default=9)
    parser.add_argument('--policy', choices=('reactive','proactive','ocn_hamilton','classical_learner'), default='reactive', help='Task policy (default: reactive)')
    parser.add_argument('--scheduler', choices=('backoff','periodic4','paced16','paced32','classical_learner','ocn_hamilton','ocn_real'),
                        help='Enable persistent after-task dissipation with this selector')
    parser.add_argument('--reservoir', help='SQLite sink outside the habitat and separate from --state')
    parser.add_argument('--reservoir-capacity', type=int, default=None, help='Sink capacity (default: 16)')
    parser.add_argument('--reaction-horizon', type=int, default=None, help='Local reaction bound (default: 8)')
    parser.add_argument('--allow-decimal', action='store_true', help='Permit canonical decimal integer strings')
    parser.add_argument('--repack-refused', action='store_true', help='Repack atomically refused local batches (new DNA/checkpoint)')
    parser.add_argument('--require-schema-binding', action='store_true', help='Reject documents without a schema digest (immutable DNA)')
    parser.add_argument('--maintenance-only', action='store_true', help='One maintenance tick on existing state; no task reads')
    args = parser.parse_args()
    if args.maintenance_only and not args.scheduler:
        parser.error('--maintenance-only requires --scheduler')
    if args.repack_refused and not args.scheduler:
        parser.error('--repack-refused requires --scheduler')
    if args.scheduler and (not args.state or not args.reservoir):
        parser.error('--scheduler requires --state and --reservoir')
    if not args.scheduler and any(v is not None for v in (args.reservoir,args.reservoir_capacity,args.reaction_horizon)):
        parser.error('Reservoir and reaction options require --scheduler')
    paths = {}
    for binding in args.source:
        if '=' not in binding:
            parser.error('Each source must be SOURCE=INITIAL_FILENAME')
        source, path = binding.split('=', 1)
        if source in paths:
            parser.error('Duplicate source')
        paths[source] = path
    try:
        options=dict(require_schema_binding=args.require_schema_binding, max_calls=args.budget, max_cache=len(paths), source_ids=tuple(paths),
                     allowed_codecs=('integer','decimal_integer') if args.allow_decimal else ('integer',))
        dna=((RepackingDNA if args.repack_refused else ScheduledDNA)(**options, scheduler=args.scheduler, emission_phase='after', aggregation='eager',
                          learning_scope='source', known_unsupported_reactive=True,
                          reaction_horizon=8 if args.reaction_horizon is None else args.reaction_horizon)
             if args.scheduler else DNA(**options))
        habitat=Path(args.habitat).resolve(strict=True)
        checkpoint = Path(args.state).resolve() if args.state else None
        if args.maintenance_only and (checkpoint is None or not checkpoint.is_file()):
            raise ValueError('Maintenance requires an existing checkpoint')
        reservoir = Path(args.reservoir).resolve() if args.reservoir else None
        for location in (checkpoint,reservoir):
            if location is not None and (location==habitat or habitat in location.parents):
                raise ValueError('State and reservoir must be outside the habitat')
        if reservoir is not None and reservoir==checkpoint:
            raise ValueError('State and reservoir must be separate files')
        # Validate checkpoint and habitat before creating a new sink.
        agent = (load_checkpoint(checkpoint, dna, args.policy) if checkpoint is not None and checkpoint.exists()
                 else (RepackingAgent if args.repack_refused else ScheduledAgent if args.scheduler else Agent)(args.policy, paths, dna=dna))
        DirectoryHabitat(habitat,dna)
        if args.scheduler:
            sink=CompactReservoir(reservoir,16 if args.reservoir_capacity is None else args.reservoir_capacity)
            tools=DissipativeHabitat(habitat,dna,sink)
            if args.maintenance_only:
                result=agent.maintain(args.step,tools,checkpoint)
            else:
                agent.step(args.step,tools)
                result=agent.finish_request(args.step,tools,checkpoint)
        else:
            result=agent.step(args.step,DirectoryHabitat(habitat,dna))
            if checkpoint is not None:save_checkpoint(agent,checkpoint)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result['help_requested'] else 0
