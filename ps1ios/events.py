"""Progress as one JSON object per line (same shape HookLink / NX2Apple parse):
{"ev":"stage","k":1,"n":9,"name":...} {"ev":"say","msg":...} {"ev":"stage_end","name":...,"ok":true,"summary":...}"""
from __future__ import annotations

import contextlib
import json
import sys


class Events:
    def __init__(self, stream=sys.stdout, human: bool = False):
        self.stream = stream
        self.human = human
        self.k = 0
        self.total = 0
        self.summary = ""

    def emit(self, **d) -> None:
        if self.human:
            if d["ev"] == "stage":
                line = f"[{d['k']}/{d['n']}] {d['name']}"
            elif d["ev"] == "stage_end":
                line = f"  {'ok' if d['ok'] else 'FAILED'}: {d.get('summary', '')}"
            else:
                line = "  " + d.get("msg", "")
            print(line, file=self.stream, flush=True)
        else:
            print(json.dumps(d), file=self.stream, flush=True)

    def say(self, msg: str) -> None:
        self.emit(ev="say", msg=msg)

    @contextlib.contextmanager
    def stage(self, name: str):
        self.k += 1
        self.summary = ""
        self.emit(ev="stage", k=self.k, n=self.total, name=name)
        try:
            yield
        except Exception as e:
            self.emit(ev="stage_end", name=name, ok=False, summary=str(e))
            raise
        self.emit(ev="stage_end", name=name, ok=True, summary=self.summary or "ok")
