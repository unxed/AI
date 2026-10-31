import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mistral_chat import parse_chat_stream

# Captured from chat.mistral.ai /api/chat (trimmed), plus a streamed-append variant.
RAW = '''15:{"json":{"type":"message","messageId":"a1","messageVersion":0,"patches":[{"op":"replace","path":"/","value":{"role":"assistant","content":"","contentChunks":null,"generationStatus":"in-progress"}}]}}
15:{"json":{"type":"message","messageId":"u0","messageVersion":0,"patches":[{"op":"replace","path":"/moderationCategory","value":"safe"}]}}
15:{"json":{"type":"message","messageId":"a1","messageVersion":0,"patches":[{"op":"replace","path":"/contentChunks","value":[{"type":"text","text":"PONG"}]}]}}
15:{"json":{"type":"message","messageId":"a1","messageVersion":0,"patches":[{"op":"append","path":"/contentChunks/0/text","value":" 42"}]}}
15:{"json":{"type":"message","messageId":"a1","messageVersion":0,"patches":[{"op":"replace","path":"/generationStatus","value":"success"}]}}
8:null
'''


def test_parse_full():
    assert parse_chat_stream(RAW) == ("success", "PONG 42")


def test_parse_partial():
    cut = RAW[:RAW.index('{"op":"append"') + 20]  # unterminated line mid-stream
    assert parse_chat_stream(cut) == ("in-progress", "PONG")
