#!/usr/bin/perl
# Minimal static web server for the offline register: 127.0.0.1 only, GET and HEAD only,
# files under the given folder only. Core Perl modules, so it runs on a stock macOS or Linux.
# Usage: perl serveur.pl FOLDER PORT
use strict;
use warnings;
use IO::Socket::INET;

my ($root, $port) = @ARGV;
die "usage: perl serveur.pl FOLDER PORT\n" unless defined $port && -d $root;

my %TYPES = (
    html  => 'text/html; charset=utf-8',
    js    => 'text/javascript; charset=utf-8',
    css   => 'text/css; charset=utf-8',
    json  => 'application/json',
    md    => 'text/plain; charset=utf-8',
    txt   => 'text/plain; charset=utf-8',
    woff2 => 'font/woff2',
    png   => 'image/png',
    jpg   => 'image/jpeg',
    jpeg  => 'image/jpeg',
    svg   => 'image/svg+xml',
    ico   => 'image/x-icon',
);
my %REASONS = (200 => 'OK', 400 => 'Bad Request', 404 => 'Not Found', 405 => 'Method Not Allowed');

my $server = IO::Socket::INET->new(
    LocalAddr => '127.0.0.1',
    LocalPort => $port,
    Listen    => 64,
    ReuseAddr => 1,
) or die "Impossible d'ouvrir le port $port : $!\n";
$SIG{CHLD} = 'IGNORE';    # reap finished children automatically

# One child per connection: a browser's idle speculative connection must not block others.
while (1) {
    my $client = $server->accept or next;
    my $pid = fork;
    if (!defined $pid || $pid) { close $client; next; }
    close $server;
    serve($client);
    exit 0;
}

sub serve {
    my ($client) = @_;
    local $SIG{ALRM} = sub { exit 0 };
    alarm 15;
    binmode $client;
    my $request = <$client>;
    return unless defined $request;
    while (defined(my $header = <$client>)) { last if $header =~ /^\r?\n\z/ }

    my ($method, $target) = $request =~ m{^([A-Z]+) (\S+) HTTP/};
    return reply($client, 400, 'text/plain', 'Bad request', 0) unless defined $target;
    return reply($client, 405, 'text/plain', 'Method not allowed', 0)
        unless $method eq 'GET' || $method eq 'HEAD';

    my ($path) = split /[?#]/, $target, 2;
    $path =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/ge;
    $path .= 'index.html' if $path =~ m{/\z};
    my $file = "$root$path";
    return reply($client, 404, 'text/plain', 'Not found', 0)
        if $path !~ m{\A/} || $path =~ m{(?:\A|/)\.\.(?:/|\z)} || $path =~ /\0/ || !-f $file;

    open my $fh, '<:raw', $file or return reply($client, 404, 'text/plain', 'Not found', 0);
    my $body = do { local $/; <$fh> };
    close $fh;
    my ($extension) = $file =~ /\.([^.\/]+)\z/;
    my $type = $TYPES{ lc($extension // '') } // 'application/octet-stream';
    reply($client, 200, $type, $body, $method eq 'HEAD');
}

sub reply {
    my ($client, $code, $type, $body, $head_only) = @_;
    print {$client} "HTTP/1.1 $code $REASONS{$code}\r\n",
        "Content-Type: $type\r\n",
        'Content-Length: ', length($body), "\r\n",
        "Cache-Control: no-cache\r\n",
        "Connection: close\r\n\r\n";
    print {$client} $body unless $head_only;
    close $client;
}
