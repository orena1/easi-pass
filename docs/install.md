# Install

EASI-PASS needs **Python 3.12**. Installing into an older one fails with errors that name the
wrong thing, so use one of the routes below rather than plain `pip`.

All three give the identical environment.

## uv

Recommended. [uv](https://docs.astral.sh/uv/) resolves and installs far faster than pip or
conda, and it downloads its own copy of Python, so nothing has to be set up first.

```bash
git clone https://github.com/orena1/easi-pass.git
cd easi-pass
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e . -c requirements.txt
```

Installing uv, if you do not have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                 # macOS, Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"      # Windows
```

Then open a new shell, or `export PATH="$HOME/.local/bin:$PATH"`.

## conda

```bash
git clone https://github.com/orena1/easi-pass.git
cd easi-pass
conda env create -f environment.yml && conda activate easipass
pip install -e . -c requirements.txt
```

## venv

Only if you already have Python 3.12. Check the version first, because the failure otherwise is
obscure:

```bash
python3 -V        # must be 3.12 or newer
python3 -m venv .venv && source .venv/bin/activate
pip install -e . -c requirements.txt
```

If `python3 -m venv` itself fails, your distribution splits it into a separate package
(`sudo apt install python3-venv` on Debian and Ubuntu).

## After installing

Activate again in every new shell: `conda activate easipass`, or `source .venv/bin/activate`
(`.venv\Scripts\activate` on Windows).

`requirements.txt` pins the tested versions, so keep `-c` on any later install into the same
environment:

```bash
pip install -e ".[notebooks,analysis]" -c requirements.txt
```

The pipeline is developed and tested on Linux, so that is where it is known to run end to end.

Cross-modal runs also need [Fiji](https://fiji.sc/)'s BigWarp for landmarks
(Plugins > BigDataViewer > Big Warp). [landmarks.md](landmarks.md) is what the pipeline needs
from you; [BigWarp_Tips.md](BigWarp_Tips.md) is how to drive BigWarp.

## GPU

Not required. Only Cellpose uses one. A full HCR FISH volume (2500 x 2500 x 100 px) segments in
a few minutes on a GPU and an hour or two without one; the demo's single plane is fine either
way. Set `gpu: false` in a cellpose block to force the CPU.

**RAM matters more:** budget roughly 25 GB while a 2048 x 2048 x 100 round is registered.

To check whether your GPU is usable:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Both halves matter. The version should end `+cu124`, since a bare `2.5.1` is a CPU-only build.
Any NVIDIA GPU works given driver **525 or newer** and a card no newer than Hopper (CUDA 12.4
does not cover the RTX 50 series). Either bound gives `False` on a machine that plainly has a
GPU, so the pipeline names the card it found, says why it could not use it, and carries on with
the CPU.

The CUDA libraries are Linux-only, so a GPU only helps there.

## Warnings you can ignore

Three appear on every run and mean nothing:

- `pynwb not installed`, from Suite2p
- `FutureWarning: You are using torch.load with weights_only=False`, from Cellpose loading its
  own model
- a `SyntaxWarning` from inside SimpleITK
