"""CLI compatibility receipts captured from the pinned pre-subparser baseline."""

import json
from pathlib import Path

import pytest

from healthcheck.cli import build_parser

LEGACY = json.loads((Path(__file__).parent / "fixtures/cli_invocations.json").read_text())


@pytest.fixture(scope="module")
def parser():
    return build_parser()


def normalized(namespace):
    return json.loads(json.dumps(vars(namespace), default=str))


@pytest.mark.parametrize("command", LEGACY["commands"])
def test_all_command_defaults_match_legacy(parser, command):
    assert normalized(parser.parse_args([command])) == {**LEGACY["defaults"], "command": command}


@pytest.mark.parametrize("case", LEGACY["invocations"], ids=lambda case: case["source"])
def test_documented_and_scheduled_invocations_match_legacy(parser, case):
    assert normalized(parser.parse_args(case["argv"])) == {**LEGACY["defaults"], **case["expected"]}


@pytest.mark.parametrize(
    "argv,expected",
    [
        (
            ["--data-dir", "serve", "serve", "--port", "8126"],
            {"command": "serve", "data_dir": "serve", "port": 8126},
        ),
        (
            ["--data-dir=first", "serve", "--data-dir", "second"],
            {"command": "serve", "data_dir": "second"},
        ),
        (
            ["--date", "2099-01-01", "garmin-capabilities", "--date", "2099-01-02"],
            {"command": "garmin-capabilities", "dates": ["2099-01-01", "2099-01-02"]},
        ),
        (
            [
                "--max-range",
                "2099-01-01",
                "2099-01-02",
                "garmin-training-phase-a",
                "--max-range",
                "2099-01-03",
                "2099-01-04",
            ],
            {
                "command": "garmin-training-phase-a",
                "max_ranges": [["2099-01-01", "2099-01-02"], ["2099-01-03", "2099-01-04"]],
            },
        ),
        (
            ["--stream=sleep", "owner-refresh", "--stream", "hrv"],
            {"command": "owner-refresh", "streams": ["sleep", "hrv"]},
        ),
        (
            ["--is-cn", "garmin-auth", "--force-reauth"],
            {"command": "garmin-auth", "is_cn": True, "force_reauth": True},
        ),
        (["--port", "-1", "serve"], {"command": "serve", "port": -1}),
        (
            ["--data-d", "profile", "serve", "--po=8126"],
            {"command": "serve", "data_dir": "profile", "port": 8126},
        ),
        (["--data-dir", "profile", "--", "serve"], {"command": "serve", "data_dir": "profile"}),
        (["serve", "--"], {"command": "serve"}),
        # The old parser accepted unused flags: tightening that here would break
        # working scripts even though they are omitted from the new help text.
        (
            ["--tag", "first", "serve", "--tag", "second"],
            {"command": "serve", "tags": ["first", "second"]},
        ),
    ],
)
def test_option_order_actions_and_legacy_abbreviations(parser, argv, expected):
    assert normalized(parser.parse_args(argv)) == {**LEGACY["defaults"], **expected}


def test_path_options_remain_paths(parser):
    args = parser.parse_args(["--auth-file", "synthetic.json", "serve"])
    assert args.auth_file == Path("synthetic.json")


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["-h"],
        ["--hel"],
        ["--data-dir", "x", "--help"],
        ["--is-cn", "--help"],
        ["--date", "2099-01-01", "--hel"],
        ["--date", "2099-01-01", "--he"],
    ],
)
def test_top_level_help_lists_commands_and_shared_flags(parser, capsys, argv):
    with pytest.raises(SystemExit) as result:
        parser.parse_args(argv)
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert all(command in help_text for command in LEGACY["commands"])
    assert "--data-dir" in help_text
    assert "--include-steps" not in help_text


@pytest.mark.parametrize("command", LEGACY["commands"])
def test_every_command_has_its_own_help(parser, capsys, command):
    with pytest.raises(SystemExit) as result:
        parser.parse_args([command, "--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert f"healthcheck {command}" in help_text
    assert "--data-dir" in help_text


@pytest.mark.parametrize(
    "command,present,absent",
    [
        ("serve", ["--app", "--port", "--tls-certfile"], ["--date", "--dry-run"]),
        (
            "owner-refresh",
            ["--stream", "--include-google-steps", "--google-steps-catchup"],
            ["--include-steps", "--reset"],
        ),
        ("garmin-training-phase-a", ["--max-range", "--max-date", "--repeat-date"], ["--format"]),
        ("garmin-training-sync", ["--start", "--end"], ["--max-range", "--activity-id"]),
        ("google-auth", ["--include-steps", "--force-reauth"], ["--stream", "--dry-run"]),
        ("google-steps", ["--date", "--family", "--apply", "--dry-run"], ["--start", "--reset"]),
        ("context-revise", ["--event-id", "--text", "--clear-tags"], ["--limit", "--history"]),
    ],
)
def test_command_help_is_scoped(parser, capsys, command, present, absent):
    with pytest.raises(SystemExit) as result:
        parser.parse_args([command, "--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert f"healthcheck {command}" in help_text
    assert "--data-dir" in help_text
    assert all(flag in help_text for flag in present)
    assert all(flag not in help_text for flag in absent)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["unknown"],
        ["serve", "--unknown"],
        ["--port", "invalid", "serve"],
        ["serve", "--port"],
        ["--max-range", "2099-01-01", "garmin-training-phase-a"],
        ["serve", "--app", "unknown"],
        ["--sta", "on", "serve"],
        ["--", "-h"],
        ["--", "--help"],
        ["--", "serve", "--"],
        ["--port", "--help"],
        ["--port", "--hel"],
        ["--is-cn", "--", "serve", "--hel"],
        ["--is-cn", "--is-cn", "--", "serve", "--is-cn"],
    ],
)
def test_parser_misuse_still_exits_nonzero(parser, argv):
    with pytest.raises(SystemExit) as result:
        parser.parse_args(argv)
    assert result.value.code == 2
