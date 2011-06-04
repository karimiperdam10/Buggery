
import idebug
import sys

# thinking about doing this via contextmanager
# with output(dbg.execute(cmd))

class CollectOutputCallbacks(idebug.OutputCallbacks):
    def __init__(self):
        self._collection = []
        self._gathering = False

    def onOutput(self, mask, text):
        if self._gathering:
            self._collection.append(text)

    def start(self):
        self._collection = []
        self._gathering = True
    def stop(self):
        self._gathering = False
    def get_output(self):
        return self._collection

    def __enter__(self):
        self.start()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
    def __str__(self):
        return self.get_output()


class DebugEventHandler(idebug.EventHandler):
    INTEREST_MASK = (idebug.DbgEng.DEBUG_EVENT_BREAKPOINT |
                     idebug.DbgEng.DEBUG_EVENT_CREATE_PROCESS |
                     idebug.DbgEng.DEBUG_EVENT_EXCEPTION)

    def __init__(self, interestmask):
        if interestmask is not None:
            self.INTEREST_MASK = interestmask
        self.handlers = {
            'INTERESTMASK': self.get_interest_mask,
            'BREAKPOINT': self.on_breakpoint
        }
        self._bp_callbacks = {}

    def get_interest_mask(self, ignored):
        return self.INTEREST_MASK
    def set_interest_mask(self, interest_mask):
        self.INTEREST_MASK = interest_mask
    def add_interest(self, interest):
        self.INTEREST_MASK |= interest
    def has_interest(self, interest):
        return bool(self.INTEREST_MASK & interest)

    def on_breakpoint(self, bp):
        if bp.id in self._bp_callbacks:
            return self._bp_callbacks[bp.id](bp)

    def handle_event(self, eventtype, event):
        try:
            retval = None
            retval = self.handlers[eventtype](event)
        except KeyError:
            retval = idebug.GO_HANDLED
        except Exception, e:
            sys.stderr.write("%r" % e)
            retval = idebug.GO_IGNORED

        if retval is None:
            retval = idebug.GO_HANDLED

        return retval

    def set_handler(self, eventtype, handler):
        self.handlers[eventtype] = handler

class AddressSpace(object):
    def __init__(self, dbg):
        self.dbg = dbg
    def __getitem__(self, offset):
        if isinstance(offset, (slice,)):
            address, count = offset.start, offset.stop-offset.start
        else:
            address, count = offset, 1
        return self.dbg.dataspaces.read(address, count)
    def __setitem__(self, offset, buf):
        if isinstance(offset, (slice,)):
            address, count = offset.start, offset.stop-offset.start
            if len(buf) != count:
                raise RuntimeError("Buffer size and slice range don't agree: %d != %d" % (len(buf), count))
        else:
            address, count = offset, len(buf)
        num = self.dbg.dataspaces.write(offset, buf)

        if num != count:
            raise RuntimeError("Short write to memory %d < %d. Inconsistent state, bailing out...", num, count)
        return self

    def find(self, pattern, address, count, alignment=1):
        return self.dbg.dataspaces.search(pattern, address, count, alignment)

class Debugger(object):
    def __init__(self, interestmask=None):
        self._output = CollectOutputCallbacks()
        self._events = DebugEventHandler(interestmask)
        self.client = idebug.Client(output_cb=self._output,
                                   event_cb=self._events)

        self.dataspaces = idebug.DataSpaces(self.client)
        self.registers = idebug.Registers(self.client)
        self.control = idebug.Control(self.client)

    def set_event_handler(self, eventtype, handler):
        interests = {
            'BREAKPOINT': idebug.DbgEng.DEBUG_EVENT_BREAKPOINT,
            'CREATEPROCESS': idebug.DbgEng.DEBUG_EVENT_CREATE_PROCESS,
        }
        self._events.set_handler(eventtype, handler)
        # should adjust set_interest_mask too
        if eventtype in interests \
                and not self._events.has_interest(interest[eventtype]):
            self.add_interest(interests[eventtype])

    def add_interest(self, interest):
        self._events.add_interest(interest)
        self.client.set_event_callbacks(self._events)

    def set_interest_mask(self, interest_mask):
        # Assuming that we can just add new interests like this
        self._events.set_interest_mask(interest_mask)
        return self.client.set_event_callbacks(self._events)

    def execute(self, cmd):
        self._output.start()
        self.control.execute(cmd)
        self.client.flush_output()
        self._output.stop()
        return self._output.get_output()

    def step_into(self): pass
    def step_over(self): pass
    def step_branch(self): pass

    def breakpoint(self, address, callback,oneshot=False,private=True,cmd=None):
        bp = self.control.set_breakpoint(address, oneshot, private, cmd)
        self._events._bp_callbacks[bp.id] = callback
        return bp

    def watchpoint(self, address, size, callback, mode='rwx', oneshot=False,private=True,cmd=None):
        bp = self.control.set_watchpoint(address, size, mode, oneshot, private, cmd)
        self._events._bp_callbacks[bp.id] = callback
        return bp

    def wait_for_event(self):
        return self.control.wait_for_event()

    def next_event(self):
        self.wait_for_event()
        return self.control.get_last_event()

    def spawn(self, cmdline):
        self.client.create_process(cmdline)

    def attach(self, pid):
        self.client.attach_process(pid)

    def detach(self):
        self.client.detach_processes()

    def terminate(self):
        self.client.terminate_processes()

    def opendump(self, path):
        self.client.open_dump_file(path)

    def writedump(self, path, mode=0):
        self.client.write_dump_file(path, mode)
