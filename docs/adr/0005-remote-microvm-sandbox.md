# 0005 Remote microVM sandbox instead of Docker

- Status: Accepted
- Date: 2026-11-19

## Context
Generated code must never run on the host. The development machine cannot run Docker (no
hardware virtualization available).

## Problem
Where and how generated tests are executed.

## Options
1. Docker locally (not possible on this machine).
2. Restricted local subprocess (not real isolation).
3. E2B cloud microVMs.
4. Modal or Daytona sandboxes.
5. GitHub Actions as an executor.
6. Remote Docker host over SSH.
7. WebAssembly (Pyodide).

## Decision
E2B microVMs behind a `CodeExecutor` interface, with a `StaticOnlyExecutor` fallback that never
executes code.

## Reasons
VM-level isolation with its own kernel; no local virtualization needed; Python SDK; network can
be switched off on a running sandbox. Spike A: sandbox ready in 3.2 s, install in 10.5 s, pytest
passed, internet confirmed blocked afterwards.

## Advantages
Stronger isolation than containers; nothing to install locally; provider swappable behind the
interface.

## Disadvantages
Generated code leaves the machine; dependency on a third-party service, its quotas and pricing;
about 40 s per run.

## Consequences
Packages are installed from a pinned constraints file before the network is cut; generated
projects target the sandbox's Python 3.11; a missing key yields `NOT_EXECUTED`, never a fake pass.

## Reconsider when
Docker or a self-hosted Firecracker host becomes available, or provider cost or limits become a
problem.
