FROM qwb-qlib-cpu:local

# RD-Agent runtime for one bounded Attempt: the driver (LLM orchestration) and the factor
# code it launches both run in this container, so the policy memory/CPU limits cover the
# whole attempt. The checkout itself is mounted at run time, so an upstream code change does
# not require rebuilding this image — only its dependencies need a rebuild.

ARG RDAGENT_VERSION=unknown

COPY requirements.txt /src/requirements.txt
RUN python -m pip install --no-cache-dir -r /src/requirements.txt

COPY pyproject.toml README.md /src/
COPY rdagent /src/rdagent
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${RDAGENT_VERSION}
# RD-Agent's setup.py imports numpy at build time, so the install must see the runtime
# environment instead of an isolated build env.
RUN python -m pip install --no-cache-dir setuptools setuptools-scm wheel \
    && python -m pip install --no-cache-dir --no-deps --no-build-isolation /src

# The mounted checkout wins over this copy (same rule as the Qlib route).
ENV PYTHONPATH=/qwb/src:/opt/qwb
WORKDIR /qwb/agent
