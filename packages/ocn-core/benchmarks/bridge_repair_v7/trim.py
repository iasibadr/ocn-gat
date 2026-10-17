def build_synthesizer(model):
    def synthesize(question, documents):
        # Find the document with the matching document_id
        for document in documents:
            if document['document_id'] == question:
                if not document['text'].strip():  # Check if the document text is empty or only whitespace
                    return dict(
                        response=dict(
                            answer="The requested document was not found or is empty.",
                            abstain=True,
                            citations=[]
                        ),
                        usage={}
                    )
                else:
                    return dict(
                        response=dict(
                            answer=document['text'].strip(),
                            abstain=False,
                            citations=[dict(document_id=document['document_id'], quote=document['text'])]
                        ),
                        usage={}
                    )
        # If no matching document is found
        return dict(
            response=dict(
                answer="The requested document was not found or is empty.",
                abstain=True,
                citations=[]
            ),
            usage={}
        )
    return synthesize
