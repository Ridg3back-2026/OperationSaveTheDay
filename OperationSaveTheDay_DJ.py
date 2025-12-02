import core
import pox.openflow.discovery
from pox.lib.addresses import IPAddr
from pox.openflow import libopenflow_01 as of
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote_plus

log = core.getLogger()

H1_IP = "10.0.0.1"
H2_IP = "10.0.0.2"

connections = {}
adjacency = {}
failed_links = set()

host_to_switch = {
    IPAddr(H1_IP): 3,
    IPAddr(H2_IP): 4
}

PRIMARY_PATH = [3, 2, 4]
BACKUP_PATH = [3, 5, 4]

def install_flow(conn, src, dst, out_port):
    fm = of.ofp_flow_mod()
    m = of.ofp_match()
    m.dl_type = 0x0800
    m.nw_src = IPAddr(src)
    m.nw_dst = IPAddr(dst)
    fm.match = m
    fm.actions.append(of.ofp_action_output(port=out_port))
    fm.idle_timeout = 30
    conn.send(fm)

def adjacency_add(link):
    a, b = link.dpid1, link.dpid2
    pa, pb = link.port1, link.port2
    adjacency.setdefault(a, {})[b] = pa
    adjacency.setdefault(b, {})[a] = pb
    log.info("ADDED adjacency: %s-%s" % (a, b))

def adjacency_remove(link):
    a, b = link.dpid1, link.dpid2
    if a in adjacency and b in adjacency[a]:
        del adjacency[a][b]
    if b in adjacency and a in adjacency[b]:
        del adjacency[b][a]
    log.warning("REMOVED adjacency: %s-%s" % (a, b))

def get_port(a, b):
    try:
        return adjacency[a][b]
    except:
        return None

def apply_path(path):
    log.info("Installing flows for path: %s" % path)
    for i in range(len(path) - 1):
        sw = path[i]
        nxt = path[i + 1]
        conn = connections.get(sw)
        out_port = get_port(sw, nxt)
        if conn and out_port:
            install_flow(conn, H1_IP, H2_IP, out_port)
            install_flow(conn, H2_IP, H1_IP, out_port)
            log.info("Flow installed on switch %s → port %s" % (sw, out_port))

def handle_failure(a, b):
    log.warning("External FAILURE reported on link %s-%s" % (a, b))
    failed_links.add((min(a, b), max(a, b)))
    apply_path(BACKUP_PATH)

def restore_link(a, b):
    log.info("External RESTORE reported on link %s-%s" % (a, b))
    failed_links.discard((min(a, b), max(a, b)))
    apply_path(PRIMARY_PATH)

def _handle_LinkEvent(event):
    link = event.link
    if event.added:
        adjacency_add(link)
    else:
        adjacency_remove(link)

def _handle_ConnectionUp(event):
    dpid = event.connection.dpid
    connections[dpid] = event.connection
    log.info("Switch %s connected" % dpid)

def _handle_PacketIn(event):
    pass

class FailureRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length_header = self.headers.get('Content-Length')
            if not length_header:
                self.send_response(411)
                self.end_headers()
                self.wfile.write(b"Missing Content-Length")
                return

            length = int(length_header)
            raw = self.rfile.read(length)
            body = raw.decode('utf-8', 'ignore')
            params = parse_qs(unquote_plus(body))
            a = int(params.get("a", [""])[0])
            b = int(params.get("b", [""])[0])

            if self.path == "/failure":
                handle_failure(a, b)
                response = f"Failure injected on {a}-{b}".encode()
            elif self.path == "/restore":
                restore_link(a, b)
                response = f"Restore injected on {a}-{b}".encode()
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Invalid endpoint.")
                return

            self.send_response(200)
            self.end_headers()
            self.wfile.write(response)

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Server error: {e}".encode())

    def log_message(self, format, *args):
        return

def start_http_server():
    try:
        server = HTTPServer(("0.0.0.0", 8000), FailureRequestHandler)
        log.info("External Failure API Server running on port 8000")
        server.serve_forever()
    except Exception as e:
        log.error(f"HTTP server failed to start: {e}")

def launch():
    pox.openflow.discovery.launch()
    core.openflow.addListenerByName("ConnectionUp", _handle_ConnectionUp)
    core.openflow.addListenerByName("PacketIn", _handle_PacketIn)
    core.openflow_discovery.addListenerByName("LinkEvent", _handle_LinkEvent)

    thread = Thread(target=start_http_server)
    thread.daemon = True
    thread.start()
 
    log.info("OperationSaveTheDay Controller launched successfully.")
