"""Diagnostic only: does not execute tools or supply an answer."""
def annotate(action,feedback):
    result=dict(feedback)
    if action.get('op')!='read' or feedback.get('ok') is not False:return result
    if feedback.get('error')=='invalid_document':
        result['source']=action['source']
        result['recovery']=dict(name='abstain',source='',path='',answer=0)
        result['explanation']='The document was rejected as invalid or ambiguous JSON. Repeating this read or changing its schema does not validate it. Call abstain for this task. A later task can retry after the producer corrects the document.'
        return result
    operation={'schema':'describe','not_found':'locate'}.get(feedback.get('error'))
    if operation is None:return result
    result['source']=action['source']
    result['recovery']=dict(name=operation,source=action['source'],path='',answer=0)
    result['explanation']=('The stored descriptor does not match this document. Call describe for this source, then read it again.'
        if operation=='describe' else 'This path was not found. Call locate for this source, then read its returned path.')
    return result


def with_progress(action,feedback,sources,verified):
    result=dict(feedback)
    result['progress']=dict(verified_sources=[s for s in sources if s in verified],
                            remaining_sources=[s for s in sources if s not in verified])
    if action.get('op')=='read':result['source']=action['source']
    return result
