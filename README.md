# Datakrash

Track yourself. Trigger actions when unreachable.



[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/karshosphere/template-python)

## How it works

A systemd timer runs `datakrash run` every `system.trigger`. Each run:

1. Asks every enabled service, in the order they appear in the config, whether there has been activity within that service's `duration`. The first one that says yes ends the run.
2. Skips a service that cannot be reached, and tells you over ntfy that its check failed to connect.
3. If no service shows activity, sends you an ntfy prompt asking for your password. You reply by publishing the password to the reply topic. A wrong reply, or none within `reply_window`, uses one attempt and sends a fresh prompt.
4. After the last attempt fails, messages your contact by email and/or SMS (whichever are set): at 0h, 1h30m and 3h, then once a day until a week has passed. Before every message the services are checked again and the reply topic is read; activity or the right password stops the rest.

If ntfy itself is unreachable, no attempt is used up: the run exits and systemd tries again in 5 minutes. Every step is saved to a state file, so a restart or reboot carries on where it left off.

## Setup

### Requirements

* Linux with systemd
* Python 3.13 and [uv](https://docs.astral.sh/uv/)
* An ntfy account with an access token and two reserved topics (or a self-hosted ntfy server). Without a token, anyone who learns the topic names can read your password replies.
* For email: an SMTP account. For SMS: a Twilio account.

### Build

```bash
$ make build
```

### Configure

1. Copy `config.example.toml` to `/etc/datakrash/config.toml` and fill it in. Every setting is described there.
2. Put secrets in `/etc/datakrash/env`, one `NAME=value` per line, matching the `*_env` keys in the config, and make it readable by root only:

   ```bash
   $ sudo install -m 600 /dev/null /etc/datakrash/env
   ```

3. Write the message for your contact to the file named in `contact.message`.
4. Set the password the challenge asks for. Only an scrypt hash is stored:

   ```bash
   $ sudo datakrash --config /etc/datakrash/config.toml set-password
   ```

5. Check that every service answers:

   ```bash
   $ datakrash --config /etc/datakrash/config.toml check
   ```

### Install the timer

```bash
$ datakrash --config /etc/datakrash/config.toml systemd-units --out ./units --user "$USER"
$ sudo cp units/datakrash.* /etc/systemd/system/
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now datakrash.timer
```

The service user needs to be able to read the config, the message file and the password hash. Its state lives in `/var/lib/datakrash/`. Follow it with `journalctl -u datakrash`.

### Drill

```bash
$ datakrash --config /etc/datakrash/config.toml drill --silent
```

Runs the whole sequence with every service treated as quiet. The ntfy prompts are real, so you can test replying, but the reply window is one minute, the contact schedule runs 3600 times faster, and messages to the contact are only logged. Nothing reaches the contact. Every log line is marked `[DRILL]`, and the real state file is left alone.

## Services

| Service  | Settings                                         | Activity means                                     |
|----------|--------------------------------------------------|----------------------------------------------------|
| `github` | `username`, optional `token`                     | any event in the user's feed; private events need a token for that user |
| `garmin` | `email`, `password`, optional `tokens` directory | a recorded activity, or steps logged on any day in the window |

### Adding a service

Add a module to `datakrash/service/` that defines one subclass of `Service` with a `check_activity(since)` method. Return `True` for activity at or after `since` (UTC), return `False` for none, and raise `CheckFailed` when the service cannot be asked. Then enable it with a `[service.<module name>]` section in the config. Its settings arrive in `self.settings`.

Notifiers work the same way in `datakrash/notifier/`, selected with `provider = "<module name>"`.



## Testing

### Run all tests

```bash
$ make test
```

### Formatting

```bash
$ make format           # format in place
$ make format-dry-run   # list files that need formatting
```



## Documentation

* [Project Structure](docs/project_structure.md): repository layout and module responsibilities




## Release

`make release` builds a wheel and an sdist into `dist/`. They install on any platform with Python 3.13.

The package version comes from the release tags through setuptools-scm, so there is nothing to bump. In CI it is the version being released; locally it is worked out from `git describe`, or `0.0.0` with no tags or no git.



## Copier Update

The project uses [Copier](https://copier.readthedocs.io/en/stable/) to manage its template. When the template is updated, the project can be easily brought up to date by running the following command from the project root:

```bash
$ copier update --defaults --answers-file .copier-py-answers.yml
```
When the `--defaults` option is used, copier update skips all previously answered questions and prompts only for newly introduced ones.

