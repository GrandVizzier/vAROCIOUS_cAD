"""Solver dispatch: the project's `simulation.solver` picks the backend module."""
from . import openems_sim, palace_sim
from .openems_sim import SimError  # noqa: F401  (one error type for every backend)

BACKENDS = {"openems": openems_sim, "palace": palace_sim}


def backend(result):
    sim = result.get("simulation")
    return BACKENDS[sim["solver"]] if sim else openems_sim


def preflight(result):
    return backend(result).preflight(result)


def run(result, out_dir, log=print):
    return backend(result).run(result, out_dir, log=log)
