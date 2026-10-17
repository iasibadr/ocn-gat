"""GAT: persistent, bounded local document agents (trusted Linux host)."""
import argparse
import json
import os
import re
from pathlib import Path
from .application import locked, lifecycle, write_lifecycle
from .document_adapter import DocumentAdapter
from .document_agent import DocumentAgent

FORMAT = 'gat.documents.v1'
ADAPTED_FORMAT = 'gat.documents.python.v1'
ISOLATED_FORMAT = 'gat.documents.python-isolated.v1'
BROKERED_FORMAT = 'gat.documents.python-brokered.v1'


def unique(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('Duplicate manifest fields')
    return result


def validate(config):
    if type(config) is not dict: raise ValueError('Invalid GAT document manifest')
    fields = {'format','habitat','documents','mission','model'}
    if config.get('format') in (ADAPTED_FORMAT, ISOLATED_FORMAT, BROKERED_FORMAT):
        fields.add('integration')
        from .agent_integration import validate_descriptor
        validate_descriptor(config.get('integration'))
        if config['format']==BROKERED_FORMAT:
            from .model_budget import validate_limit
            fields.add('model_call_limit')
            validate_limit(config.get('model_call_limit'))
    elif config.get('format') != FORMAT:
        raise ValueError('Invalid GAT document manifest')
    if 'authorized_models' in config:
        models=config['authorized_models']
        if (config.get('format')!=BROKERED_FORMAT or type(models) is not list or not 1<=len(models)<=8
            or any(type(m) is not str or not m.strip() or len(m.encode())>256 for m in models)
            or len(set(models))!=len(models) or config.get('model') not in models):
            raise ValueError('Invalid broker model authorization catalogue')
        fields.add('authorized_models')
    if 'synthesis_profile' in config:
        if config.get('format') not in (FORMAT,BROKERED_FORMAT) or config['synthesis_profile']!='answerability-v1':
            raise ValueError('Invalid synthesis profile for this execution mode')
        fields.add('synthesis_profile')
    if 'evolution' in config:
        if config.get('format') not in (ISOLATED_FORMAT,BROKERED_FORMAT): raise ValueError('Evolution requires isolated execution')
        from .candidate_adoption import validate_evolution
        validate_evolution(config['evolution'])
        fields.add('evolution')
    if set(config) != fields: raise ValueError('Invalid GAT document manifest')
    ids = config['documents']
    if (type(ids) is not list or not 1 <= len(ids) <= 8
        or any(type(i) is not str or not i.strip() or len(i)>128 for i in ids)
        or len(set(ids)) != len(ids)):
        raise ValueError('One to eight distinct document identifiers required')
    if type(config['mission']) is not str or not config['mission'].strip() or len(config['mission'].encode())>4096:
        raise ValueError('Invalid mission')
    if type(config['model']) is not str or not config['model'].strip():
        raise ValueError('Model identifier required')
    if type(config['habitat']) is not str or not Path(config['habitat']).is_absolute():
        raise ValueError('Absolute habitat required')


def separate(root, habitat):
    if root == habitat or root in habitat.parents or habitat in root.parents:
        raise ValueError('Instance and habitat must be separate, non-nested directories')


def load(instance):
    root = Path(instance).resolve(strict=True)
    with (root/'instance.json').open('rb') as f:
        raw = f.read(65537)
    if len(raw)>65536: raise ValueError('Manifest too large')
    config = json.loads(raw, object_pairs_hook=unique)
    validate(config)
    separate(root, Path(config['habitat']).resolve())
    return root, config


def create(instance, habitat, documents, mission, model='qwen3.5:9b', *, expected_sha256=None, integration=None, isolated=False, model_calls=None, synthesis_profile='standard', authorized_models=None):
    if type(isolated) is not bool or (isolated and integration is None):
        raise ValueError('Isolation requires a prepared integration and boolean mode')
    if model_calls is not None:
        from .model_budget import validate_limit
        validate_limit(model_calls)
        if not isolated: raise ValueError('Model mediation requires isolation')
    root = Path(instance).resolve()
    habitat = Path(habitat).resolve(strict=True)
    if not habitat.is_dir(): raise ValueError('Habitat directory required')
    if type(documents) is not dict: raise ValueError('Document mapping required')
    config = dict(format=FORMAT, habitat=str(habitat), documents=list(documents), mission=mission, model=model)
    if integration is not None:
        from .agent_integration import Integration
        if type(integration) is not Integration: raise ValueError('Prepared integration required')
        config.update(format=ISOLATED_FORMAT if isolated else ADAPTED_FORMAT, integration=integration.descriptor())
    if model_calls is not None:
        config.update(format=BROKERED_FORMAT,model_call_limit=model_calls)
    if synthesis_profile not in ('standard','answerability-v1'):raise ValueError('Unknown synthesis profile')
    if synthesis_profile!='standard':config['synthesis_profile']=synthesis_profile
    if authorized_models is not None:
        if type(authorized_models) is not list:raise ValueError('Model authorization catalogue must be a list')
        config['authorized_models']=list(authorized_models)
    validate(config)
    if expected_sha256 is not None:
        if (type(expected_sha256) is not dict or set(expected_sha256) != set(documents)
            or any(type(d) is not str or re.fullmatch('[0-9a-f]{64}',d) is None for d in expected_sha256.values())):
            raise ValueError('Expected digest required for every document')
    separate(root, habitat)
    root.mkdir(exist_ok=False)
    # Failed enrollment leaves an inactive directory, never an executable agent.
    with locked(root):
        adapter = DocumentAdapter(habitat, root/'documents.json')
        for ident, path in documents.items():
            snapshot = adapter.bind(ident, path)
            if expected_sha256 is not None and snapshot.sha256 != expected_sha256[ident]:
                raise ValueError('Document changed since design; redesign required')
        if integration is not None: integration.write(root)
        with (root/'instance.json').open('x') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        if model_calls is not None:
            from .model_budget import initialize
            initialize(root,model_calls)
        write_lifecycle(root, 'active')
    return status(root)


def status(instance):
    root, config = load(instance)
    with locked(root):
        result=dict(instance=str(root), **config, lifecycle=lifecycle(root))
        if config['format']==BROKERED_FORMAT:
            from .model_budget import read
            result['model_budget']=read(root,config['model_call_limit'])
        return result


def set_paused(instance, paused):
    if type(paused) is not bool: raise ValueError('Boolean required')
    root, config = load(instance)
    with locked(root):
        previous = lifecycle(root)
        if previous == 'uninitialized':
            raise RuntimeError('Incomplete instance; create a new instance')
        desired = 'paused' if paused else 'active'
        write_lifecycle(root, desired)
        return dict(instance=str(root), lifecycle=desired, changed=previous != desired)


def sources(instance):
    root, config = load(instance)
    with locked(root):
        bindings = DocumentAdapter(config['habitat'], root/'documents.json').bindings()
        if set(bindings) != set(config['documents']):
            raise ValueError('Document bindings do not match the instance manifest')
        return dict(instance=str(root), lifecycle=lifecycle(root), fresh_source_check=False,
                    documents=[dict(document_id=ident, **bindings[ident]) for ident in config['documents']])


def update_document(instance, ident, path, expected_current, expected_new):
    root, config = load(instance)
    with locked(root):
        state = lifecycle(root)
        if state not in ('active','paused'): raise RuntimeError('Incomplete instance')
        if ident not in config['documents']: raise ValueError('Document is outside the instance mission')
        adapter = DocumentAdapter(config['habitat'], root/'documents.json')
        document = adapter.accept_version(ident, path, expected_current_sha256=expected_current,
                                          expected_new_sha256=expected_new)
        return dict(document_id=ident, path=document.path, sha256=document.sha256,
                    previous_sha256=expected_current, bytes_read=document.bytes_read, lifecycle=state)


def run(instance, *, question=None, model=None, synthesizer=None, record=False,
        learned_models=None,feedback_rubric=None,minimum_observations=3,reward_weights=None,
        acceptance_suite=None,expected_authority=None,preserve_acceptance=False,feedback_scope='mission'):
    if feedback_scope not in ('mission','document_versions'):raise ValueError('Unknown feedback scope')
    if feedback_scope!='mission' and not (record or learned_models is not None):
        raise ValueError('Version feedback scope requires recording')
    if type(preserve_acceptance) is not bool:raise ValueError('Boolean acceptance preservation required')
    if preserve_acceptance and acceptance_suite is None:raise ValueError('Acceptance preservation requires an execution gate')
    if (acceptance_suite is None)!=(expected_authority is None):
        raise ValueError('Acceptance gate requires its authority snapshot')
    if reward_weights is not None and learned_models is None:
        raise ValueError('Reward weights require learned model selection')
    if learned_models is not None:
        if model is not None or synthesizer is not None:raise ValueError('Learned choice cannot override model or synthesizer')
        record=True
    if type(record) is not bool:raise ValueError('Boolean recording flag required')
    if record and synthesizer is not None:raise ValueError('Cannot attribute feedback to an unpinned override')
    root, config = load(instance)
    with locked(root):
        root, config = load(root)
        if lifecycle(root) != 'active': raise RuntimeError('Instance is paused or uninitialized')
        if acceptance_suite is not None:
            from .maintenance_policy import authority
            if config['format'] not in (ISOLATED_FORMAT,BROKERED_FORMAT):raise ValueError('Maintained execution requires isolation')
            if authority(config)!=expected_authority:raise ValueError('Maintenance authority changed before execution')
        if config['format']==BROKERED_FORMAT:
            from .run_feedback import check_broker_models
            check_broker_models(config,[config['model'] if model is None else model])
            if learned_models is not None:check_broker_models(config,learned_models)
        if record:
            from .run_feedback import prepare,save
            if acceptance_suite is None:
                from .memory_maintenance import before_run_locked
                before_run_locked(root,config)
                receipt_directory=prepare(root)
        adapter = DocumentAdapter(config['habitat'], root/'documents.json')
        document_versions=None
        if feedback_scope=='document_versions':
            bindings=adapter.bindings()
            document_versions={ident:bindings[ident]['sha256'] for ident in config['documents']}
        selected = config['model'] if model is None else model
        effective_question=config['mission'] if question is None else question
        if config['format'] in (ADAPTED_FORMAT, ISOLATED_FORMAT, BROKERED_FORMAT):
            if synthesizer is not None: raise ValueError('Cannot override a pinned integration')
            from .agent_integration import PinnedSynthesizer
            pinned = PinnedSynthesizer(root, config['integration'], selected,revisioned='evolution' in config)
            if acceptance_suite is not None:
                from .candidate_evaluation import evaluate,PreExecutionAcceptanceError
                from .agent_integration import Integration
                if preserve_acceptance and config.get('evolution'):
                    from .cumulative_adoption import read_retained,combine
                    acceptance_suite=combine(read_retained(root,config['evolution']['suite_sha256']),acceptance_suite)
                from .candidate_evaluation import validate_suite
                validate_suite(acceptance_suite)
                kind='request' if config['format']==BROKERED_FORMAT else 'response'
                if any(set(case['expected'])!={kind} for case in acceptance_suite['cases']):
                    raise ValueError('Acceptance execution contract mismatch')
                gate=evaluate(Integration(pinned.source,pinned.entrypoint),acceptance_suite)
                if not gate['accepted']:raise PreExecutionAcceptanceError(gate)
                if record:
                    # Rejected preflight is not a mission and must not archive
                    # memory or allocate a receipt before the repair decision.
                    from .memory_maintenance import before_run_locked
                    before_run_locked(root,config)
                    receipt_directory=prepare(root)
        selection=None
        if learned_models is not None:
            from .run_feedback import choose_model
            selection=choose_model(root,config,effective_question,learned_models,feedback_rubric,
                                   minimum_observations=minimum_observations,reward_weights=reward_weights,document_versions=document_versions)
            selected=selection['model']
        identity=None
        if record:
            from .run_feedback import model_identity
            identity=model_identity(config,selected)
            if selection is not None and identity!=selection['model_digest']:
                raise ValueError('Model identity changed during selection')
        if config['format'] in (ADAPTED_FORMAT, ISOLATED_FORMAT, BROKERED_FORMAT):
            pinned.model=selected
            if config['format'] == BROKERED_FORMAT:
                from .agent_integration import Integration
                from .model_broker import BrokeredSynthesizer
                from .model_budget import reserve,read
                budget=read(root,config['model_call_limit'])
                if budget['used']>=budget['limit']: raise RuntimeError('Persistent model call budget exhausted')
                synthesizer=BrokeredSynthesizer(Integration(pinned.source,pinned.entrypoint),selected,
                    reserve_call=lambda:reserve(root,config['model_call_limit']),synthesis_profile=config.get('synthesis_profile','standard'))
            elif config['format'] == ISOLATED_FORMAT:
                from .agent_integration import Integration
                from .sandbox_trial import IsolatedSynthesizer
                synthesizer = IsolatedSynthesizer(Integration(pinned.source,pinned.entrypoint),selected)
            else:
                synthesizer = pinned
        agent = (DocumentAgent.from_local_model(adapter, selected,profile=config.get('synthesis_profile','standard')) if synthesizer is None
                 else DocumentAgent(adapter, synthesizer))
        try:
            result=agent.answer(effective_question, tuple(config['documents']))
        except Exception as exc:
            if not record:raise
            from .run_feedback import RecordedRunError
            receipt=save(receipt_directory,config,effective_question,selected,None,failure=exc,model_digest=identity,document_versions=document_versions)
            raise RecordedRunError(receipt) from exc
        if record:
            if identity is not None:
                usage=result['usage'].get('model_usage',result['usage'])
                if usage.get('model_digest')!=identity:raise ValueError('Model identity changed before synthesis; outcome not attributed')
            if selection is not None:result={**result,'learned_selection':selection}
            receipt=save(receipt_directory,config,effective_question,selected,result,model_digest=identity,document_versions=document_versions)
            result={**result,'run_receipt':receipt}
        return result



def trial(instance, agent_file, *, question=None, factory='build_synthesizer', allow_model=False):
    """Try candidate bytes without replacing or executing the installed bridge."""
    from .agent_integration import prepare
    from .sandbox_trial import IsolatedSynthesizer
    if type(allow_model) is not bool: raise ValueError('Boolean model authorization required')
    integration=prepare(agent_file,factory)
    root, config=load(instance)
    with locked(root):
        if lifecycle(root)!='active': raise RuntimeError('Instance is paused or uninitialized')
        adapter=DocumentAdapter(config['habitat'],root/'documents.json')
        if allow_model:
            from .model_broker import BrokeredSynthesizer
            reservation=None
            if config['format']==BROKERED_FORMAT:
                from .model_budget import reserve,read
                budget=read(root,config['model_call_limit'])
                if budget['used']>=budget['limit']: raise RuntimeError('Persistent model call budget exhausted')
                reservation=lambda:reserve(root,config['model_call_limit'])
            synthesizer=BrokeredSynthesizer(integration,config['model'],reserve_call=reservation,synthesis_profile=config.get('synthesis_profile','standard'))
        else:
            synthesizer=IsolatedSynthesizer(integration,config['model'])
        agent=DocumentAgent(adapter,synthesizer)
        return agent.answer(config['mission'] if question is None else question,tuple(config['documents']))


def read_json(path):
    with Path(path).open('rb') as f: raw = f.read(65537)
    if len(raw)>65536: raise ValueError('JSON input too large')
    return json.loads(raw, object_pairs_hook=unique)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('models')
    archive=sub.add_parser('archive-receipts',help='Archive evaluated receipts before removing their active copies')
    archive.add_argument('instance');archive.add_argument('--reservoir',required=True);archive.add_argument('--limit',type=int,default=64)
    retire=sub.add_parser('retire-feedback',help='Archive older outcomes before removing them from active learning')
    retire.add_argument('instance');retire.add_argument('--action',required=True);retire.add_argument('--rubric',required=True)
    retire.add_argument('--reservoir',required=True);retire.add_argument('--keep-per-pair',type=int,default=32)
    retire.add_argument('--limit',type=int,default=256)
    learned=sub.add_parser('run-learned',help='Choose among explicitly authorized models using observed success')
    learned.add_argument('instance');learned.add_argument('--models',nargs='+',required=True)
    learned.add_argument('--feedback-scope',choices=('mission','document_versions'),default='mission')
    learned.add_argument('--rubric',required=True);learned.add_argument('--question')
    learned.add_argument('--minimum-observations',type=int,default=3)
    learned.add_argument('--success-weight',type=float,default=1.)
    learned.add_argument('--quality-weight',type=float,default=0.)
    learned.add_argument('--intervention-penalty',type=float,default=0.)
    memory_config=sub.add_parser('memory-configure',help='Authorize bounded archive-before-run housekeeping')
    memory_config.add_argument('instance');memory_config.add_argument('--reservoir',required=True)
    memory_config.add_argument('--cycles',type=int,required=True)
    for name in ('memory-status','memory-disable'):
        memory_command=sub.add_parser(name);memory_command.add_argument('instance')
    feedback_parser=sub.add_parser('feedback',help='Record explicit operator feedback for a recorded run')
    feedback_parser.add_argument('instance');feedback_parser.add_argument('--run-id',required=True)
    feedback_parser.add_argument('--rubric',required=True);feedback_parser.add_argument('--success',choices=('yes','no'),required=True)
    feedback_parser.add_argument('--quality',type=float,required=True);feedback_parser.add_argument('--interventions',type=int,required=True)
    maintenance=sub.add_parser('maintenance-configure',help='Persist explicit bounded maintenance authority; no daemon')
    maintenance.add_argument('instance');maintenance.add_argument('--contract',required=True);maintenance.add_argument('--suite',required=True)
    maintenance.add_argument('--designer-model',required=True);maintenance.add_argument('--audit-root',required=True)
    maintenance.add_argument('--cycles',type=int,required=True);maintenance.add_argument('--candidate-limit',type=int,default=8)
    maintenance.add_argument('--preserve-acceptance',action='store_true',help='Retain acceptance during authorized maintenance and execution')
    maintenance.add_argument('--observe-runtime',action='store_true');maintenance.add_argument('--acceptance-feedback',action='store_true')
    for command in ('maintenance-tick','maintenance-status'):sub.add_parser(command).add_argument('instance')
    maintained=sub.add_parser('run-maintained',help='Consume an authorized maintenance cycle, then execute after acceptance')
    maintained.add_argument('instance');maintained.add_argument('--question')
    maintained.add_argument('--feedback-scope',choices=('mission','document_versions'),default='mission')
    maintained.add_argument('--models',nargs='+',help='Choose only from sufficiently observed authorized models')
    maintained.add_argument('--rubric')
    maintained.add_argument('--minimum-observations',type=int,default=3)
    maintained.add_argument('--record',action='store_true',help='Record the executed mission for explicit outcome feedback')
    maintained.add_argument('--repair-on-failure',action='store_true',help='Spend a maintenance cycle only after a conclusive acceptance failure')
    hybrid=sub.add_parser('repair-hybrid',help='Bounded local search then at most one designer proposal')
    hybrid.add_argument('instance');hybrid.add_argument('--suite',required=True);hybrid.add_argument('--contract',required=True)
    hybrid.add_argument('--output',required=True);hybrid.add_argument('--designer-model',required=True)
    hybrid.add_argument('--candidate-limit',type=int,default=8)
    hybrid.add_argument('--observe-runtime',action='store_true');hybrid.add_argument('--acceptance-feedback',action='store_true')
    local=sub.add_parser('repair-local',help='Bounded isolated syntactic search without model calls')
    local.add_argument('instance');local.add_argument('--suite',required=True);local.add_argument('--output',required=True)
    local.add_argument('--candidate-limit',type=int,default=8)
    local.add_argument('--preserve-acceptance',action='store_true',help='Require retained and new acceptance cases')
    hybrid.add_argument('--preserve-acceptance',action='store_true',help='Preserve acceptance in both local and designer repair')
    repair_parser=sub.add_parser('repair',help='One designer proposal and conditional isolated adoption')
    repair_parser.add_argument('--acceptance-feedback',action='store_true',help='Share aggregate acceptance differences, never expected texts, with designer')
    repair_parser.add_argument('--proposal-format',choices=['source','lines'],default='source')
    repair_parser.add_argument('--observe-runtime',action='store_true',help='Send a compact structural observation from offline execution to the designer')
    repair_parser.add_argument('instance'); repair_parser.add_argument('--contract',required=True)
    repair_parser.add_argument('--suite',required=True); repair_parser.add_argument('--designer-model',required=True)
    repair_parser.add_argument('--output',required=True)
    repair_parser.add_argument('--preserve-acceptance',action='store_true',help='Retain previous acceptance cases during repair and adoption')
    achange=sub.add_parser('adopt', help='Evaluate current and candidate bridges, adopting only a passing improvement')
    achange.add_argument('instance'); achange.add_argument('--agent-file',required=True)
    achange.add_argument('--suite',required=True); achange.add_argument('--expected-current-sha256',required=True)
    achange.add_argument('--factory',default='build_synthesizer')
    achange.add_argument('--preserve-acceptance',action='store_true',help='Require retained and new acceptance cases; refuse missing retained evidence')
    back=sub.add_parser('rollback'); back.add_argument('instance')
    back.add_argument('--expected-current-sha256',required=True)
    e = sub.add_parser('evaluate', help='Run a finite host-defined acceptance suite in isolation; no promotion')
    e.add_argument('--agent-file', required=True); e.add_argument('--suite', required=True)
    e.add_argument('--factory', default='build_synthesizer')
    d = sub.add_parser('design')
    d.add_argument('--habitat', required=True); d.add_argument('--catalog', required=True)
    d.add_argument('--mission', required=True); d.add_argument('--designer-model', required=True)
    d.add_argument('--model', default='qwen3.5:9b'); d.add_argument('--output', required=True)
    i = sub.add_parser('instantiate'); i.add_argument('instance'); i.add_argument('--plan', required=True)
    i.add_argument('--synthesis-profile',choices=('standard','answerability-v1'),default='standard')
    a = sub.add_parser('adapt', help='Integrate a Python bridge; trusted host execution unless --isolated')
    a.add_argument('--synthesis-profile',choices=('standard','answerability-v1'),default='standard')
    a.add_argument('--authorized-models',nargs='+',help='Explicit broker model catalogue; default remains pinned')
    a.add_argument('--model-calls', type=int, help='Persistent total model attempt budget; requires --isolated')
    a.add_argument('--isolated', action='store_true', help='Persist offline Bubblewrap execution; no host fallback')
    a.add_argument('instance'); a.add_argument('--plan', required=True)
    a.add_argument('--agent-file', required=True); a.add_argument('--factory', default='build_synthesizer')
    c = sub.add_parser('create')
    c.add_argument('instance'); c.add_argument('--habitat', required=True)
    c.add_argument('--synthesis-profile',choices=('standard','answerability-v1'),default='standard')
    c.add_argument('--document', action='append', required=True)
    c.add_argument('--mission', required=True); c.add_argument('--model', default='qwen3.5:9b')
    ev = sub.add_parser('evidence', help='Structured extraction on an ordinary local instance; explicit optional organ')
    ev.add_argument('instance'); ev.add_argument('--spec', required=True)
    ev.add_argument('--mode', choices=('serial','organ'), default='serial')
    ev.add_argument('--max-cells', type=int, default=3)
    ev.add_argument('--max-model-calls', type=int, default=8)
    ev.add_argument('--persist-memory', action='store_true', help='Reuse version-keyed bounded extraction memory across invocations')
    r = sub.add_parser('run'); r.add_argument('instance'); r.add_argument('--question'); r.add_argument('--model')
    r.add_argument('--feedback-scope',choices=('mission','document_versions'),default='mission')
    r.add_argument('--record',action='store_true',help='Save a bounded receipt for later explicit feedback')
    t = sub.add_parser('trial', help='Offline isolated candidate trial; does not install or promote code')
    t.add_argument('--allow-model', action='store_true', help='Allow one host-mediated synthesis with the configured model')
    t.add_argument('instance'); t.add_argument('--agent-file', required=True)
    t.add_argument('--factory', default='build_synthesizer'); t.add_argument('--question')
    u = sub.add_parser('update-document', help='Host-authorized exact-version update, no model call')
    u.add_argument('instance'); u.add_argument('--document', required=True); u.add_argument('--path', required=True)
    u.add_argument('--expected-current-sha256', required=True); u.add_argument('--expected-new-sha256', required=True)
    for name in ('status','pause','resume','sources'):
        sub.add_parser(name).add_argument('instance')
    args = parser.parse_args()
    try:
        if args.command == 'models':
            from .local_models import installed_models
            result = dict(provider='ollama_loopback', models=installed_models())
        elif args.command == 'archive-receipts':
            from .receipt_archive import archive_receipts
            result=archive_receipts(args.instance,args.reservoir,limit=args.limit)
        elif args.command == 'retire-feedback':
            from .run_feedback import retire_feedback
            result=retire_feedback(args.instance,args.action,rubric=args.rubric,reservoir=args.reservoir,
                                   keep_per_pair=args.keep_per_pair,limit=args.limit)
        elif args.command == 'run-learned':
            result=run(args.instance,question=args.question,learned_models=args.models,
                       feedback_rubric=args.rubric,minimum_observations=args.minimum_observations,feedback_scope=args.feedback_scope,
                       reward_weights=dict(success_weight=args.success_weight,quality_weight=args.quality_weight,
                                           intervention_penalty=args.intervention_penalty))
        elif args.command == 'feedback':
            from .run_feedback import feedback
            result=feedback(args.instance,args.run_id,rubric=args.rubric,success=args.success=='yes',quality=args.quality,interventions=args.interventions)
        elif args.command == 'run-maintained':
            from .maintained_run import run_maintained
            result=run_maintained(args.instance,question=args.question,repair_on_failure=args.repair_on_failure,record=args.record,feedback_scope=args.feedback_scope,
                                  learned_models=args.models,feedback_rubric=args.rubric,minimum_observations=args.minimum_observations)
        elif args.command == 'memory-configure':
            from .memory_maintenance import configure
            result=configure(args.instance,args.reservoir,args.cycles)
        elif args.command in ('memory-status','memory-disable'):
            from .memory_maintenance import status as memory_status
            result=memory_status(args.instance,disable=args.command=='memory-disable')
        elif args.command == 'maintenance-configure':
            from .maintenance_policy import configure
            result=configure(args.instance,args.contract,read_json(args.suite),args.designer_model,args.audit_root,args.cycles,candidate_limit=args.candidate_limit,observe_runtime=args.observe_runtime,share_acceptance_feedback=args.acceptance_feedback,preserve_acceptance=args.preserve_acceptance)
        elif args.command in ('maintenance-tick','maintenance-status'):
            from .maintenance_policy import tick,status as maintenance_status
            result=tick(args.instance) if args.command=='maintenance-tick' else maintenance_status(args.instance)
        elif args.command == 'repair-hybrid':
            from .hybrid_repair import hybrid_repair
            from .bridge_repair import LocalBridgeRepairer
            result=hybrid_repair(args.instance,args.contract,read_json(args.suite),LocalBridgeRepairer(args.designer_model,proposal_format='lines'),args.output,limit=args.candidate_limit,observe_runtime=args.observe_runtime,share_acceptance_feedback=args.acceptance_feedback,preserve_acceptance=args.preserve_acceptance)
        elif args.command == 'repair-local':
            from .local_repair import local_repair
            result=local_repair(args.instance,read_json(args.suite),args.output,limit=args.candidate_limit,preserve_acceptance=args.preserve_acceptance)
        elif args.command == 'repair':
            from .bridge_repair import repair,LocalBridgeRepairer
            result=repair(args.instance,args.contract,read_json(args.suite),LocalBridgeRepairer(args.designer_model,proposal_format=args.proposal_format),args.output,observe_runtime=args.observe_runtime,share_acceptance_feedback=args.acceptance_feedback,preserve_acceptance=args.preserve_acceptance)
        elif args.command == 'adopt':
            from .candidate_adoption import adopt
            from .cumulative_adoption import adopt_cumulative
            from .agent_integration import prepare
            adoption=adopt_cumulative if args.preserve_acceptance else adopt
            result=adoption(args.instance,prepare(args.agent_file,args.factory),read_json(args.suite),args.expected_current_sha256)
        elif args.command == 'rollback':
            from .candidate_adoption import rollback
            result=rollback(args.instance,args.expected_current_sha256)
        elif args.command == 'evaluate':
            from .candidate_evaluation import evaluate
            from .agent_integration import prepare
            result=evaluate(prepare(args.agent_file,args.factory),read_json(args.suite))
        elif args.command == 'design':
            from .designer import design, LocalDocumentDesigner
            # Reserve output before paying for inference; never overwrite a plan.
            with Path(args.output).open('x') as output:
                result = design(args.habitat, read_json(args.catalog), args.mission, args.model, LocalDocumentDesigner(args.designer_model))
                json.dump(result, output, ensure_ascii=False, indent=2)
                output.flush(); os.fsync(output.fileno())
        elif args.command == 'instantiate':
            from .designer import instantiate
            result = instantiate(args.instance, read_json(args.plan),synthesis_profile=args.synthesis_profile)
        elif args.command == 'adapt':
            from .designer import instantiate
            from .agent_integration import prepare
            result = instantiate(args.instance, read_json(args.plan), integration=prepare(args.agent_file, args.factory), isolated=args.isolated, model_calls=args.model_calls,synthesis_profile=args.synthesis_profile,authorized_models=args.authorized_models)
        elif args.command == 'create':
            documents = {}
            for value in args.document:
                if '=' not in value: raise ValueError('Document must be ID=RELATIVE_PATH')
                ident, path = value.split('=', 1)
                if ident in documents: raise ValueError('Duplicate document identifier')
                documents[ident] = path
            result = create(args.instance, args.habitat, documents, args.mission, args.model,synthesis_profile=args.synthesis_profile)
        elif args.command == 'evidence':
            from .evidence_run import run_evidence
            with open(args.spec,'rb') as source: raw=source.read(16385)
            if len(raw)>16384: raise ValueError('Evidence specification too large')
            spec=json.loads(raw,object_pairs_hook=unique)
            if (type(spec) is not dict or 'fields' not in spec
                    or set(spec)-{'fields','question','quantity_scales'}):
                raise ValueError('Explicit evidence field specification required')
            result=run_evidence(args.instance,**spec,mode=args.mode,max_cells=args.max_cells,
                                max_model_calls=args.max_model_calls,persist_memory=args.persist_memory)
        elif args.command == 'run': result = run(args.instance, question=args.question, model=args.model,record=args.record,feedback_scope=args.feedback_scope)
        elif args.command == 'trial': result = trial(args.instance, args.agent_file, question=args.question, factory=args.factory, allow_model=args.allow_model)
        elif args.command == 'status': result = status(args.instance)
        elif args.command == 'sources': result = sources(args.instance)
        elif args.command == 'update-document':
            result = update_document(args.instance, args.document, args.path, args.expected_current_sha256, args.expected_new_sha256)
        else: result = set_paused(args.instance, args.command == 'pause')
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.command=='evaluate' and not result['accepted'] else 0


if __name__ == '__main__': raise SystemExit(main())
