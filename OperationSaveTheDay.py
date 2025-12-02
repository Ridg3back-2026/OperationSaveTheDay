from pox.core import core
from pox.lib.packet import ethernet
from pox.lib.addresses import IPAddr
from pox.openflow import libopenflow_01 as of
import pox.openflow.discovery
import subprocess

log = core.getLogger()

H1_IP = "10.0.0.1"
H2_IP = "10.0.0.2"

connections = {}
failed_links = set()

PRIMARY_PATH = [3, 2, 4]  # main route
BACKUP_PATH = [3, 5, 4]   # reroute on failure

# Installs OpenFlow rules on switches to forward packets between specific IPs
def install_flow(connection, src, dst, out_port):
    fm = of.ofp_flow_mod()
    m = of.ofp_match()
    m.dl_type = 0x0800
    m.nw_src = IPAddr(src)
    m.nw_dst = IPAddr(dst)
    fm.match = m
    fm.actions.append(of.ofp_action_output(port=out_port))
    connection.send(fm)

# Monitors and logs IP traffic for debugging
def trafficSniffer(event):
    pkt = event.parsed
    if pkt and pkt.type == ethernet.IP_TYPE:
        ip = pkt.find('ipv4')
        if ip:
            log.info("PacketIn %s -> %s on switch %s", ip.srcip, ip.dstip, event.dpid)

# Determines and activates backup path when link failures occur
def computePath(failed):
    log.info("Failure detected on link: %s", failed)
    path = [3, 5, 4]
    log.info("Using backup path: %s", path)
    updateFlows(path)

# Configures all switches in a path with bidirectional flow rules (most complex function with detailed port mappings)
def updateFlows(path):
    log.info("Installing flows for path: %s", path)
    
    if path == PRIMARY_PATH:  # [3, 2, 4]
        for sw in path:
            conn = connections.get(sw)
            if not conn:
                continue
            
            if sw == 3:
                # S3: eth1 <-> H1, eth2 <-> S2, eth3 <-> S5
                out_to_H2 = 2  # towards S2
                out_to_H1 = 1  # back towards H1
            elif sw == 2:
                # S2: eth1 <-> S3, eth2 <-> S4
                out_to_H2 = 2  # towards S4/H2
                out_to_H1 = 1  # back towards S3/H1
            elif sw == 4:
                # S4: eth1 <-> S2, eth2 <-> H2, eth3 <-> S5
                out_to_H2 = 2  # towards H2
                out_to_H1 = 1  # back towards S2/H1
            else:
                continue
            
            # Forward H1 -> H2
            install_flow(conn, H1_IP, H2_IP, out_to_H2)
            # Forward H2 -> H1
            install_flow(conn, H2_IP, H1_IP, out_to_H1)
    
    elif path == BACKUP_PATH:  # [3, 5, 4]
        for sw in path:
            conn = connections.get(sw)
            if not conn:
                continue
            
            if sw == 3:
                # S3: eth1 <-> H1, eth2 <-> S2, eth3 <-> S5
                out_to_H2 = 3  # towards S5
                out_to_H1 = 1  # back towards H1
            elif sw == 5:
                # S5: eth1 <-> S3, eth2 <-> S4
                out_to_H2 = 2  # towards S4/H2
                out_to_H1 = 1  # back towards S3/H1
            elif sw == 4:
                # S4: eth1 <-> S2, eth2 <-> H2, eth3 <-> S5
                out_to_H2 = 2  # towards H2
                out_to_H1 = 3  # back towards S5/H1
            else:
                continue
            
            # Forward H1 -> H2
            install_flow(conn, H1_IP, H2_IP, out_to_H2)
            # Forward H2 -> H1
            install_flow(conn, H2_IP, H1_IP, out_to_H1)
    
    log.info("Flow installation complete.")

# Processes packets that don't match existing rules and installs appropriate flows
def _handle_PacketIn(event):
    pkt = event.parsed
    if pkt and pkt.type == ethernet.IP_TYPE:
        ip = pkt.find('ipv4')
        if ip:
            if (ip.srcip == IPAddr(H1_IP) and ip.dstip == IPAddr(H2_IP)) or \
               (ip.srcip == IPAddr(H2_IP) and ip.dstip == IPAddr(H1_IP)):
                
                # Choose path depending on failure
                if len(failed_links) > 0:
                    path = BACKUP_PATH
                else:
                    path = PRIMARY_PATH
                
                updateFlows(path)

# Stores switch connections when they connect to the controller
def _handle_ConnectionUp(event):
    connections[event.dpid] = event.connection

# Detects link failures and triggers failover
def _handle_LinkEvent(event):
    link = (event.link.dpid1, event.link.dpid2)
    if not event.added:
        log.warning("Link failed: %s", link)
        failed_links.add(link)
        computePath(link)

# Main entry point that initializes the controller and starts all services
def launch():
    pox.openflow.discovery.launch()
    
    core.openflow.addListenerByName("ConnectionUp", _handle_ConnectionUp)
    core.openflow.addListenerByName("PacketIn", _handle_PacketIn)
    
    # Helper that waits for discovery module to start before registering link events
    def _after_boot():
        import time
        while not hasattr(core, "openflow_discovery"):
            time.sleep(0.2)
        core.openflow_discovery.addListenerByName("LinkEvent", _handle_LinkEvent)
        log.info("LinkEvent listener registered successfully.")
    
    from threading import Thread
    Thread(target=_after_boot).start()
    
    log.info("OperationSaveTheDay Controller launched successfully.")
    updateFlows(PRIMARY_PATH)