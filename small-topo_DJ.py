#!/usr/bin/env python3

from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch, Host
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink

def myNetwork():
    net = Mininet(topo=None, build=False, ipBase='10.0.0.0/8',
                  link=TCLink, autoSetMacs=True, autoStaticArp=True)

    info('* Adding controller\n')
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    info('* Add switches\n')
    s2 = net.addSwitch('s2', cls=OVSKernelSwitch)
    s3 = net.addSwitch('s3', cls=OVSKernelSwitch)
    s4 = net.addSwitch('s4', cls=OVSKernelSwitch)
    s5 = net.addSwitch('s5', cls=OVSKernelSwitch)

    info('* Add hosts\n')
    h1 = net.addHost('h1', cls=Host, ip='10.0.0.1/8', defaultRoute=None)
    h2 = net.addHost('h2', cls=Host, ip='10.0.0.2/8', defaultRoute=None)

    info('* Add links\n')
    # Primary path links (H1 - S3 - S2 - S4 - H2)
    net.addLink(h1, s3) # H1 <-> S3
    net.addLink(s3, s2) # S3 <-> S2
    net.addLink(s2, s4) # S2 <-> S4
    net.addLink(s4, h2) # S4 <-> H2

    # Backup path (s3<-> S5 <-> s4)
    net.addLink(s3, s5) # s3<-> S5
    net.addLink(s5, s4) # s5 <-> S4

    info('* Starting network\n')
    net.build()

    info('* Starting controllers\n')
    for controller in net.controllers:
        controller.start()

    info('* Starting switches\n')
    for switch in [s2, s3, s4, s5]:
        net.get(switch.name).start([c0])

    info('* Testing connectivity\n')
    net.pingAll() # Test that all hosts can reach each other

    info('* CLI\n')    
    CLI(net)

    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    myNetwork()
