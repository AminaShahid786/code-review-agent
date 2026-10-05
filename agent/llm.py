import os
import time
import ollama
 
# Override with: set SLM_MODEL=qwen2.5-coder:3b   (PowerShell: $env:SLM_MODEL="qwen2.5-coder:3b")
DEFAULT_MODEL = os.environ.get("SLM_MODEL", "qwen-refactor-7b")
 
 
def call_slm(prompt: str, model: str = None, temperature: float = 0.2) -> str:
    model = model or DEFAULT_MODEL
    start = time.time()
    print(f"      [calling {model} ...]", end="", flush=True)
 
    chunks = []
    try:
        stream = ollama.generate(
            model=model,
            prompt=prompt,
            options={"temperature": temperature, "num_predict": 400},
            keep_alive="30m",
            stream=True,
        )
        last_dot = time.time()
        for chunk in stream:
            piece = chunk.get("response", "")
            chunks.append(piece)
            # print a dot every ~5 seconds so you know it's alive, not frozen
            if time.time() - last_dot > 5:
                print(".", end="", flush=True)
                last_dot = time.time()
    except KeyboardInterrupt:
        print(f"\n      [interrupted after {time.time()-start:.1f}s]")
        raise
 
    elapsed = time.time() - start
    print(f" done in {elapsed:.1f}s")
    return "".join(chunks)
 