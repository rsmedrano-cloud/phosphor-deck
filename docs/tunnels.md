---
layout: default
title: Tunnels
permalink: /tunnels/
---

[Home](/) · [Concepts](/concepts/) · [Install](/install/) · [Patterns](/patterns/) · [The profile](/profile/) · [Commands](/commands/) · [Keys](/keys/) · [Screens](/phones/) · [Workspaces](/workspaces/) · [Mentions](/mentions/) · [The deck in a browser](/web/) · **Tunnels** · [Clipboard](/clipboard/) · [Privacy](/privacy/) · [Troubleshooting](/troubleshooting/)

---


Keep the ssh tunnels you already defined up, all the time. Your
`~/.ssh/config` stays the source of truth:

    Host db-box
        HostName db.example.org
        # mysql
        LocalForward 33307 127.0.0.1:3306

`phosphor tunnel on db-box` checks ssh logs in with a key, adds
`[[tunnels]] host = "db-box"` to the profile and starts a systemd unit that
runs `ssh -N db-box`: ssh opens exactly the forwards the config gives that
host, and the unit reconnects when the link drops. Port 33307 on the brain now
reaches the remote 3306.

    phosphor tunnel              list hosts, forwards and whether each port listens
                                 (on a terminal: pick one to turn on or off)
    phosphor tunnel on HOST
    phosphor tunnel off HOST     stop it and remove it from the profile

The wizard offers the hosts it finds (default no), setup has a tunnels entry,
the + menu a "tunnels" tab, `phosphor up` starts them, and doctor reports them.
A comment right above a LocalForward names it in the list.

Two things to know:

- the forwards listen on the brain's 127.0.0.1: its other users can reach them;
- the brain keeps a key that logs into those hosts (maybe as root): narrow it
  on the other side.

Tunnels need key login (they run unattended; BatchMode never waits on a
password). `Include` files in the ssh config aren't read.
