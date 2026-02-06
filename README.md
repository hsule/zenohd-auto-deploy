# Zenohd Auto Deploy

A submodule of [congestion_aware_routing](https://github.com/NEWSLabNTU/congestion_aware_routing).

Automatically deploys Zenoh nodes (routers, publishers, subscribers) as Docker containers, with TAP/veth network interfaces for ns-3 integration.

## How It Works

`launch_routers.py` reads `NETWORK_CONFIG.json5` and for each node:

1. Creates a tmux session
2. Starts a Docker container (`--network none`)
3. Creates TAP interfaces, bridges, and veth pairs to connect the container to ns-3
4. Assigns IP addresses inside the container
5. Launches the appropriate Zenoh binary (`zenohd` / `z_pub` / `z_sub`) with the configured endpoints and peer connections

On shutdown (Ctrl-C / SIGTERM), all containers, bridges, TAP interfaces, and tmux sessions are cleaned up automatically.

## Usage

This script is typically invoked via the parent project:

```bash
# From the congestion_aware_routing root
./script/run_zenoh.sh
```

Or run directly:

```bash
cd zenohd-auto-deploy
python3 launch_routers.py
```

The script reads `NETWORK_CONFIG.json5` in the current directory. This file is copied from `script/topology/<experiment_name>/` by `build_ns3.sh`.

## Configuration

See `NETWORK_CONFIG_DEFAULT.json5` for the template with documentation. Key fields:

| Field | Description |
|-------|-------------|
| `experiment` | Experiment name. Logs are saved under `experiment_data/<experiment>/` |
| `docker_image.tag` | Docker image to use for containers |
| `docker_image.clean_first` | Pull a fresh image before launching |
| `volume` | Path to Zenoh binaries, mounted into the container |
| `nodes.<id>.role` | `"pub"`, `"sub"`, or omit for router |
| `nodes.<id>.zid` | Zenoh runtime identifier (128-bit hex) |
| `nodes.<id>.listen_endpoints` | List of `"tcp/<ip>:<port>"` endpoints |
| `links` | Connections between nodes (`a`, `a_idx`, `b`, `b_idx`, optional `cap` in Mbps) |

## Requirements

- Python 3 with `json5` module
- Docker
- `sudo` (for TAP/bridge/netns operations)
- `tmux`