#!/bin/bash
# Registers this Mac as the repository's self-hosted runner, isolated from the
# person who owns it. Run once, from that person's account, WITHOUT sudo — it
# asks for the password itself:
#
#     bash scripts/setup-mac-runner.sh
#
# What it does, and why:
#
# 1. Creates a hidden standard account, `ghrunner`, with a random password
#    nobody keeps. The repository is public, so a job is code from GitHub; it
#    must not run as someone holding an org-admin GitHub token and SSH keys.
# 2. Closes the owner's home folder to other accounts (chmod 700). macOS
#    creates homes as drwxr-x--- for the `staff` group, which every standard
#    account belongs to, so without this the new account could read the
#    owner's files — including this project's .env. Undo with chmod 750.
# 3. Downloads the runner, checks it against the SHA-256 GitHub publishes in
#    its release notes, and registers it with the label `observatoire-video`.
#    The registration token is requested through the owner's own `gh` login,
#    handed on through standard input, and never printed or put on a command
#    line where another process could read it.
# 4. Starts it as a launchd daemon running as `ghrunner`, so it survives a
#    reboot and needs nobody logged in. The Mac must still be awake.
#
# Undo everything: see README § Self-hosted runner.
set -euo pipefail

RUNNER_USER=ghrunner
VERSION=2.338.2
SHA256=25a065af409ffa317ab4d5a3b614dd15fc9c40f2172bc1b35a1b1258e919a388
REPO=ESSEC-METALAB/ia-presidentielle
NAME=metalab-mac
LABEL=edu.essec.metalab.actions-runner
PLIST=/Library/LaunchDaemons/$LABEL.plist
# What jobs find on PATH: Homebrew carries ffmpeg and ollama. It is written into
# the runner's .path at registration, which is where jobs read it from.
JOB_PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

if [ "$(id -u)" -ne 0 ]; then
  # The owner's half: their gh login, their keychain. The token lasts an hour.
  TOKEN=$(gh api -X POST "repos/$REPO/actions/runners/registration-token" --jq .token)
  exec sudo bash "$0" <<<"$TOKEN"
fi
[ -n "${SUDO_USER:-}" ] || { echo "Run it from your own account: bash $0" >&2; exit 1; }
read -r TOKEN
OWNER_HOME=$(dscl . -read "/Users/$SUDO_USER" NFSHomeDirectory | awk '{print $2}')
RUNNER_HOME=/Users/$RUNNER_USER
RUNNER_DIR=$RUNNER_HOME/actions-runner

for tool in ffmpeg ollama; do
  [ -x "/opt/homebrew/bin/$tool" ] || { echo "/opt/homebrew/bin/$tool is missing" >&2; exit 1; }
done

echo "1/4 account $RUNNER_USER"
if id "$RUNNER_USER" >/dev/null 2>&1; then
  echo "    exists, kept"
else
  sysadminctl -addUser "$RUNNER_USER" -fullName "GitHub Actions runner" \
    -password "$(openssl rand -base64 32)" -home "$RUNNER_HOME"
  [ -d "$RUNNER_HOME" ] || createhomedir -c -u "$RUNNER_USER" >/dev/null
  dscl . -create "/Users/$RUNNER_USER" IsHidden 1
fi

echo "2/4 closing $OWNER_HOME to other accounts"
chmod 700 "$OWNER_HOME"

echo "3/4 runner $VERSION"
if [ -f "$RUNNER_DIR/.runner" ]; then
  echo "    already registered, kept"
else
  # Single quotes: the variables below are expanded by this inner shell, from
  # the environment it is given, never by splicing text into its script.
  sudo -u "$RUNNER_USER" env -i HOME="$RUNNER_HOME" PATH="$JOB_PATH" DIR="$RUNNER_DIR" \
    VERSION="$VERSION" SHA256="$SHA256" REPO="$REPO" NAME="$NAME" \
    bash -euo pipefail -c '
      read -r TOKEN
      mkdir -p "$DIR" && cd "$DIR"
      curl -fsSL -o runner.tar.gz \
        "https://github.com/actions/runner/releases/download/v$VERSION/actions-runner-osx-arm64-$VERSION.tar.gz"
      echo "$SHA256  runner.tar.gz" | shasum -a 256 -c -
      tar xzf runner.tar.gz && rm runner.tar.gz
      ./config.sh --unattended --url "https://github.com/$REPO" --token "$TOKEN" \
        --name "$NAME" --labels observatoire-video --work _work --replace
    ' <<<"$TOKEN"
fi

echo "4/4 launchd daemon $LABEL"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>UserName</key><string>$RUNNER_USER</string>
  <key>WorkingDirectory</key><string>$RUNNER_DIR</string>
  <key>ProgramArguments</key><array><string>$RUNNER_DIR/run.sh</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$RUNNER_HOME</string>
    <key>PATH</key><string>$JOB_PATH</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$RUNNER_DIR/runner.log</string>
  <key>StandardErrorPath</key><string>$RUNNER_DIR/runner.log</string>
</dict>
</plist>
EOF
chown root:wheel "$PLIST"
chmod 644 "$PLIST"
launchctl bootout system "$PLIST" 2>/dev/null || true
launchctl bootstrap system "$PLIST"

echo
echo "Done. The runner '$NAME' should show as online within a minute:"
echo "  gh api repos/$REPO/actions/runners --jq '.runners[] | .name + \" \" + .status'"
echo "Its log: sudo tail -f $RUNNER_DIR/runner.log"
