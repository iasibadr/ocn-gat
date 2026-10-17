"""Conservative per-request context selection; byte counts are not tokenization."""
WINDOWS=(4096,8192,16384)
TEMPLATE_MARGIN=1536


def select_context(messages, output_tokens=512):
    if (type(messages) is not list or not messages or len(messages)>64
        or type(output_tokens) is not int or output_tokens<1):
        raise ValueError('Invalid context request')
    prompt_bytes=0
    for message in messages:
        if (type(message) is not dict or set(message)!={'role','content'}
            or type(message['role']) is not str or type(message['content']) is not str):
            raise ValueError('Plain role/content messages required')
        prompt_bytes+=len(message['content'].encode('utf-8'))
    required=prompt_bytes+output_tokens+TEMPLATE_MARGIN
    for window in WINDOWS:
        if required<=window:
            return dict(requested_window=window,prompt_content_bytes=prompt_bytes,
                reserved_output_tokens=output_tokens,template_margin=TEMPLATE_MARGIN,
                conservative_allowance=required)
    raise ValueError('Prompt exceeds maximum conservative context allowance')


def check_context_usage(prompt_tokens, plan):
    if (type(prompt_tokens) is not int or prompt_tokens<0
        or prompt_tokens+plan['reserved_output_tokens']+plan['template_margin']>plan['requested_window']):
        raise ValueError('Reported prompt usage exceeds requested context allowance')
