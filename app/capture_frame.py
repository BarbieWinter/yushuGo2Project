import collections
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_go.msg.dds_ import AudioData_

from config import GO2_IFACE


def handler(message):
    data = bytes(message.data)
    print(len(data), data.hex(), collections.Counter(data).most_common(12), flush=True)
    raise SystemExit


ChannelFactoryInitialize(0, GO2_IFACE)
subscriber = ChannelSubscriber("rt/audiosender", AudioData_)
subscriber.Init(handler, 1)
time.sleep(5)
