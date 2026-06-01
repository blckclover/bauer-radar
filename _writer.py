import pathlib
chunks = []
path = pathlib.Path(r"C:\Users\bauer\Projects\dividend-analyzer\analyze_msft_aapl.py")
path.write_text("".join(chunks), encoding="utf-8")
print("wrote", path, "bytes", path.stat().st_size)