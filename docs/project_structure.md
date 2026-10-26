# Deadman Switch Structure

## Overview

A command-line tool, run by a systemd timer, that looks for recent activity on a set of services. When there is none, it challenges the owner for a password over ntfy, and when that fails it messages a contact on a schedule. Each run is short unless a challenge or a contact schedule is in progress, and all progress is kept in a state file so a restart resumes it.

## Top-Level Layout

* `deadman_switch/`: the package
* `tests/`: pytest suite; `tests/fakes.py` holds the fake clock, ntfy server, services and notifiers
* `config.example.toml`: every configuration setting, documented
* `docs/`: this file

## Runtime Package

* `main.py`: command-line entry point (`run`, `check`, `drill`, `set-password`, `systemd-units`) and the wiring between modules
* `config.py`: reads and validates `config.toml`, parses durations, resolves `*_env` secrets
* `watch.py`: one run of the switch: service checks, the challenge, then the contact schedule
* `challenge.py`: prompts for the password over ntfy and counts attempts
* `ntfy.py`: publishes to and polls ntfy topics
* `password.py`: scrypt hashing and verification of the challenge password
* `state.py`: the state file, written atomically, and the phases a run moves through (`armed`, `challenge`, `fired`, `spent`)
* `clock.py`: the UTC wall clock, replaced in tests
* `units.py`: renders the systemd service and timer
* `service/`: activity services, one module each, discovered by name (`github`, `garmin`)
* `notifier/`: contact notifiers, one module each, discovered by provider name (`smtp`, `twilio`, plus `printer` for drills)
