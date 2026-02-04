#!/usr/bin/env python3
import signal
import os
import sys
import subprocess
import json
import json5
import time
from datetime import datetime

def signal_handler(sig):
    print(f"\nReceived signal:{sig}, leaving...\n")
    
    if node_list:
        # print("Cleaning up tmux sessions for all nodes...\n")
        # os.chdir("experiment_data")
        for node in node_list:
            try:
                node.cleanup()
                print(f"Successfully killed tmux session for Node {node.id}\n")
            except Exception as e:
                # print(f"Failed to kill tmux session for Node {node.id}: {e}\n")
                print(f"An error occurred while performing the cleanup for Node {node.id}: {e}\n")

    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    os.killpg(process_group_id, signal.SIGTERM)
    sys.exit(0)


class Node():
    def __init__(self, id, config):
        self.id = id
        self.config = config

        if config.get('zid').get('set'):
            self.zid = config.get('zid').get('value')
        else:
            self.zid = False
            
        self.listen_endpoints = config.get('listen_endpoints') 
        self.container_name = f"zenohd_{self.id}"
        self.volume = self.config.get('volume') or network_config.get('volume')
        self.role = self.config.get('role', 'router') 
        
        self.cleanup()
        
        self.run_docker()
        time.sleep(0.5) 
        
        self.setup_network_interfaces()
        self.launch_zenoh()
    
    def launch_zenoh(self):
        launch_cmd = f"docker exec -e RUST_LOG=trace -it {self.container_name} ./zenoh/target/x86_64-unknown-linux-musl/fast/"
        
            
        if self.role == "pub":
            print(f"Launching publisher {self.container_name}")
            launch_cmd += "examples/z_pub"
        elif self.role == "sub":
            print(f"Launching subscriber {self.container_name}")
            launch_cmd += "examples/z_sub"
        else:
            print(f"Lauching zenohd {self.container_name}")
            launch_cmd += "zenohd"
            launch_cmd += " --adminspace-permissions rw"
            
            if self.zid:
                launch_cmd += f" -i {self.zid}"
                
        for ep in self.listen_endpoints:
            launch_cmd += f" -l {ep}"
            

        if self.role == "router":    
            peer_capacities = {} # 儲存 {Target ZID: Capacity}
            
            rid = str(self.id)     
            peer_eps = []
            for link in links:
                target_node_id = None
                capacity = link.get("cap")
                
                if link.get("a") == rid:
                    target_node_id = link["b"]
                    eps = nodes[target_node_id]["listen_endpoints"]
                    idx = link["b_idx"]
                    peer_eps.append(eps[idx])
                elif link.get("b") == rid:
                    target_node_id = link["a"]
                    eps = nodes[target_node_id]["listen_endpoints"]
                    idx = link["a_idx"]
                    peer_eps.append(eps[idx])
                
                if target_node_id is not None and capacity is not None:
                    target_node_config = nodes.get(target_node_id)
                    target_zid = target_node_config.get("zid").get("value")  
                    peer_capacities[target_zid] = int(capacity)
                    

            if peer_capacities:
                capacities_json_str = json.dumps(peer_capacities)
                launch_cmd += f" --cfg='peer_caps:{capacities_json_str}'"

            for ep in peer_eps:
                launch_cmd += f" -e {ep}"
                
        launch_cmd += f" > >(tee ./{self.container_name}.log) 2> >(tee ./{self.container_name}_err.log >&2)"
        tmux_cmd = f"tmux send-keys -t {self.container_name} '{launch_cmd}' C-m"
        
        self.run_shell_command(tmux_cmd)
        
        
    def setup_netns_veth(self, tid, addr):
        name = f"{self.id}_{tid}"
        
        self.run_shell_command(f"sudo ip tuntap add tap_{name} mode tap")
        self.run_shell_command(f"sudo ip link set tap_{name} promisc on up")
        
        self.run_shell_command(f"sudo ip link add name br_{name} type bridge")
        self.run_shell_command(f"sudo ip link set br_{name} up")       
        self.run_shell_command(f"sudo ip link set tap_{name} master br_{name}")
        
        self.run_shell_command(f"sudo iptables -I FORWARD -m physdev --physdev-is-bridged -i br_{name}  -j ACCEPT")

        pid = subprocess.check_output(f"docker inspect --format '{{{{ .State.Pid }}}}' {self.container_name}", shell=True).decode().strip()
        
        self.run_shell_command("sudo mkdir -p /var/run/netns")
        self.run_shell_command(f"sudo ln -sf /proc/{pid}/ns/net  /var/run/netns/{pid}") 
              
        self.run_shell_command(f"sudo ip link add internal_{name}  type veth peer name external_{name}")       
        self.run_shell_command(f"sudo ip link set internal_{name}  master br_{name}")       
        self.run_shell_command(f"sudo ip link set internal_{name}  up")       
        self.run_shell_command(f"sudo ip link set external_{name}  netns {pid}")       

        self.run_shell_command(f"sudo ip netns exec {pid}  ip link set dev external_{name} name eth{tid}")       
        self.run_shell_command(f"sudo ip netns exec {pid}  ip link set eth{tid} up")       
        self.run_shell_command(f"sudo ip netns exec {pid}  ip addr add {addr}/24 dev eth{tid}") 
        
    def setup_network_interfaces(self):
        for idx, ep in enumerate(self.listen_endpoints):
            addr = ep.split('/')[1].split(':')[0]  # e.g. 10.0.1.1
            self.setup_netns_veth(idx, addr)


    def run_shell_command(self, command):
        print(f"Running command: {command}\n")
        subprocess.run(command, shell=True, check=True)

    def cleanup_netns_veth(self, tid):
        name = f"{self.id}_{tid}"
        
        self.run_shell_command(f"sudo iptables -D FORWARD -m physdev --physdev-is-bridged -i br_{name} -j ACCEPT 2>/dev/null || true")
        
        self.run_shell_command(f"sudo ip link del br_{name} 2>/dev/null || true")
        self.run_shell_command(f"sudo ip link del tap_{name} 2>/dev/null || true")
        self.run_shell_command(f"sudo ip link del internal_{name} 2>/dev/null || true")
        self.run_shell_command(f"sudo ip link del external_{name} 2>/dev/null || true")
        
    def cleanup(self):
        print(f"Cleaning up for Node {self.id}...\n")
        
        for idx in range(len(self.listen_endpoints)):
            self.cleanup_netns_veth(idx)
        self.run_shell_command("sudo rm -f /var/run/netns/* 2>/dev/null || true")
        self.run_shell_command(f"docker container rm -f {self.container_name} 2>/dev/null || true")
        self.run_shell_command(f"tmux kill-session -t {self.container_name} 2>/dev/null || true")

    def run_docker(self):
        print(f"Running docker {self.id}...\n")
        
        chdir_command = f"mkdir -p {base_dir} && cd {base_dir} && "
        volume_arg = ""
        if self.volume:
            host_path = os.path.abspath(self.volume)
            host_project_dir = os.environ.get('HOST_PROJECT_DIR')
            if host_project_dir:
                # Remap container path to host path for Docker socket mount
                container_project_dir = os.path.abspath(os.path.join(os.getcwd(), '..'))
                host_path = host_path.replace(container_project_dir, host_project_dir, 1)
            volume_arg = f"-v {host_path}:/zenoh"

        docker_run_cmd = f"docker run -dit --name {self.container_name} --network none --rm --entrypoint /bin/sh {volume_arg} {image}"
        if image_clean:
            clean_image = f"docker rmi {image} 2>/dev/null || true && "
            docker_run_cmd = clean_image + chdir_command + docker_run_cmd
        else:
            docker_run_cmd = chdir_command + docker_run_cmd
        base_command = f"tmux new-session -d -s {self.container_name} && tmux send-keys -t {self.container_name} '{docker_run_cmd}"
        base_command += "; echo $? > /tmp/exit_code' C-m"

        self.run_shell_command(base_command)


if __name__ == "__main__":
    process_group_id = os.getpgid(os.getpid())
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


    try:
        # Load configuration from the JSON5 file
        with open('NETWORK_CONFIG.json5', 'r') as config_file:
            network_config = json5.load(config_file)
        experiment_name = network_config.get('experiment')
        image_config = network_config.get('docker_image')
        image = image_config.get('tag')
        image_clean = image_config.get('clean_first')
        user_name = network_config.get('user_name')
        nodes = network_config.get('nodes', {})
        links = network_config.get('links', [])

        run_ts = datetime.now().strftime('%Y-%m-%d_%H:%M:%S')
        base_dir = f"experiment_data/{experiment_name}/{run_ts}"
        # os.makedirs(base_dir, exist_ok=False)
        # os.chdir(base_dir)
        
        node_list = []    
        for node_id, node_config in nodes.items():
            node_list.append(Node(node_id, node_config))

        print("All nodes have been launched.\n")

        signal.pause()
    
    except Exception:
        for node in node_list:
            print("ERROR: CLEANING UP")
            node.cleanup()