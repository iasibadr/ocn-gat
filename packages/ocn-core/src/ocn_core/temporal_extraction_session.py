"""Read/extract/capture orchestration for an integrator-supplied extractor.

No retry or semantic certification. The host retains responsibility for the
extractor's execution, usage report and authorization to invoke its model.
"""
import json
from .experience_memory import label
from .temporal_evidence import instant
from .temporal_document_memory import capture, _path


def extract_and_capture(adapter,state,extractor,observed_at,*,subject,predicate,max_context_bytes=16384):
    """Call extractor once with snapshots, then pin those same source versions.

    extractor receives one JSON-compatible request and returns exactly
    {'extraction': <grounded_temporal object>, 'usage': <dict>}.
    A rejected result creates no new memory batch. No automatic inference or
    source version upgrade is performed on subsequent memory queries.
    """
    label(subject);label(predicate)
    if not callable(extractor):raise ValueError('Callable extractor required')
    if type(max_context_bytes) is not int or not 1<=max_context_bytes<=32768:
        raise ValueError('Invalid extraction context budget')
    if type(observed_at) is not dict or not 1<=len(observed_at)<=16:
        raise ValueError('One to sixteen host-observed sources required')
    observed=dict(observed_at)
    for value in observed.values():instant(value)
    path=_path(adapter,state)
    if path.exists():raise FileExistsError('Memory batch already exists')
    if not path.parent.is_dir():raise ValueError('Memory parent must exist')
    documents={ident:adapter.read(ident) for ident in observed}
    expected={ident:doc.sha256 for ident,doc in documents.items()}
    request=dict(subject=subject,predicate=predicate,documents=[
        dict(source_id=ident,sha256=doc.sha256,text=doc.text,observed_at=observed[ident])
        for ident,doc in documents.items()])
    size=len(json.dumps(request,ensure_ascii=False).encode('utf-8'))
    if size>max_context_bytes:raise ValueError('Extraction context budget exceeded before inference')
    # The callable may mutate its request; authority and digests stay outside it.
    response=extractor(request)
    if (type(response) is not dict or set(response)!={'extraction','usage'}
        or type(response['usage']) is not dict):raise ValueError('Invalid extraction envelope')
    receipt=capture(adapter,path,response['extraction'],observed,subject=subject,predicate=predicate,
                    expected_source_sha256=expected)
    return dict(**receipt,usage=response['usage'],context_bytes=size,extractor_invocations=1)
