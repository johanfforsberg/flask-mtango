"""
Simple implementation of the Tango REST API proposal v0.1 (incomplete)
https://bitbucket.org/hzgwpn/mtango/wiki/Tango%20REST%20API%20Proposal.%20Ver.%200.1

Note: This is an exploration and likely to deviate from the proposed standard.
"""

from collections import OrderedDict
import json
import time

from flask import Blueprint, request, Response, jsonify
import numpy as np
import PyTango
from PyTango.utils import str_2_obj

from ttldict import TTLDict


tango = Blueprint('tango', __name__)


class TangoEncoder(json.JSONEncoder):

    def default(self, obj):
        """
        Convert TANGO values into something JSON encodable.
        """
        if isinstance(obj, np.ndarray):
            # Probably images should be base64 encoded or something, what does
            # the specification say?
            return obj.tolist()
        elif isinstance(obj, PyTango.DevState):
            return str(obj)
        # Let the base class default method raise the TypeError
        return json.JSONEncoder(self, obj)


class CachedMethod(object):

    """A cached wrapper for a DB method."""

    def __init__(self, method, ttl=10):
        self.cache = TTLDict(default_ttl=ttl)
        self.method = method

    def __call__(self, *args):
        if args in self.cache:
            return self.cache[args]
        value = self.method(*args)
        self.cache[args] = value
        return value


class CachedDatabase(object):

    """A TANGO database wrapper that caches 'get' methods"""

    _db = PyTango.DeviceProxy("sys/database/2")
    _methods = {}

    def __init__(self, ttl):
        self._ttl = ttl

    def __getattr__(self, method):
        if not method.startswith("Get"):
            # caching 'set' methods doesn't make any sense anyway
            # TODO: check that this really catches the right methods
            return getattr(self._db, method)
        if method not in self._methods:
            self._methods[method] = CachedMethod(getattr(self._db, method),
                                                 ttl=self._ttl)
        return self._methods[method]


# Cache database read calls for a while to save the DB from load
db = CachedDatabase(ttl=10)

# Keep a cache of device proxies
# TODO: does this actually work? Are the proxies really cleaned up
# after they are deleted?
MAX_PROXIES = 100
device_proxies = OrderedDict()


def get_device_proxy(devname):
    "Keep a cache of the MAX_PROXIES last used proxies"
    if devname in device_proxies:
        return device_proxies[devname]
    proxy = PyTango.DeviceProxy(devname)
    if len(device_proxies) == MAX_PROXIES:
        oldest = device_proxies.keys()[0]
        del device_proxies[oldest]
    device_proxies[devname] = proxy
    return proxy

db_proxy = get_device_proxy("sys/database/2")


def stringify_error(error):
    return {
        "reason": error.reason,
        "description": error.desc,
        "severity": str(error.severity),
        "origin": error.origin
    }


def make_error_response(e):
    resp = Response(json.dumps({
        "errors": [stringify_error(error) for error in e],
        "quality": "FAILURE",
        "timestamp": time.time()
    }), mimetype="application/json")
    resp.status_code = 500  # correct code?
    return resp


# ******* ROUTES *********


#### DEVICES ####

@tango.route('/devices')
def get_devices():
    args = request.args
    wildcard = args.get("wildcard", "*")
    devices = db.DbGetDeviceWideList(wildcard)
    data = json.dumps([
        {"name": d, "href": "/devices/%s" % d}
        for d in devices
    ])
    return Response(data, mimetype="application/json")


@tango.route('/devices/<domain>/<family>/<member>')
def get_device(domain, family, member):

    device = "%s/%s/%s" % (domain, family, member)
    # We return the State and Status of the device.
    # Note: this seems a bit redundant since the same thing
    # can be accomplished with get_device_attributes, e.g.
    #   GET /devices/a/b/c/attributes?State&Status
    try:
        proxy = get_device_proxy(device)
    except PyTango.DevFailed as e:
        return make_error_response(e)
    state, status = proxy.read_attributes(["State", "Status"])
    # TODO: patchin together the info from several sources here, is it
    # possible to be more efficient? Also, parallelize db and proxy calls
    dev_info = proxy.info()
    db_info = db.DbGetDeviceInfo(device)[1]
    imp_info = proxy.import_info()
    info = dict(
        classname=dev_info.dev_class,
        exported=imp_info.exported,
        hostname=db_info[4],
        ior=db_info[1],
        is_taco=False,  # ?
        last_exported=db_info[5],
        last_unexported=db_info[6],
        name=db_info[0],
        server=db_info[3],
        pid=0,  # FIXME
        version=db_info[4]
    )
    attributes = list(proxy.get_attribute_list())
    dev_commands = proxy.command_list_query()
    commands = [cmd.cmd_name for cmd in dev_commands]
    properties = list(proxy.get_property_list("*"))
    # TODO: do list conversion in JSON encoder instead?
    data = json.dumps(dict(state=str(state.value),
                           status=status.value,
                           info=info, attributes=attributes,
                           commands=commands, properties=properties,
                           _links={
                               "_parent": "/devices",
                               "_self": "/devices/%s" % device}))
    return Response(data, mimetype="application/json")


@tango.route('/devices/<domain>/<family>/<member>/state', methods=["GET"])
def get_device_state(domain, family, member):
    device = "%s/%s/%s" % (domain, family, member)
    try:
        proxy = get_device_proxy(device)
    except PyTango.DevFailed as e:
        return make_error_response(e)
    state, status = proxy.read_attributes(["State", "Status"])
    # TODO: patchin together the info from several sources here, is it
    # possible to be more efficient? Also, parallelize db and proxy calls
    # TODO: do list conversion in JSON encoder instead?
    data = json.dumps(dict(
        state=str(state.value),
        status=status.value,
        _links={
            "_state": "/devices/%s/attributes/State" % device,
            "_status": "/devices/%s/attributes/Status" % device,
            "_parent": "/devices/%s" % device,
            "_self": "/devices/%s/state" % device}))
    return Response(data, mimetype="application/json")


#### ATTRIBUTES ####

@tango.route('/devices/<domain>/<family>/<member>/attributes',
             methods=["GET", "PUT"])
def get_put_device_attributes(domain, family, member):
    "Return all config parameters about the attribute"
    device = "%s/%s/%s" % (domain, family, member)
    try:
        proxy = get_device_proxy(device)
    except PyTango.DevFailed as e:
        return make_error_response(e)

    results = []
    if request.method == "PUT":
        args = request.args
        infos = proxy.get_attribute_config(args.keys())
        for attr_info in infos:
            attr = attr_info.name
            str_value = args[attr]
            value = str_2_obj(str_value, attr_info.data_type)
            if attr_info.writable in (PyTango.AttrWriteType.READ_WRITE,
                                      PyTango.AttrWriteType.READ_WITH_WRITE):
                # if possible, we write and read in one call...
                da = proxy.write_read_attribute(attr, value)
            else:
                # Inefficient; we should write/read all the attributes in one
                # call!
                proxy.write_attribute(attr, value)
                da = proxy.read_attribute(attr)
            if attr_info.data_type == PyTango.DevState:
                value = str(da.value)
            else:
                value = da.value
            results.append(dict(
                name=attr,
                value=value,
                quality=str(da.quality),
                timestamp=da.time.totime(),
                _links="..."
            ))
    else:
        attributes = proxy.get_attribute_list()
        for attr in attributes:
            results.append({
                "name": attr,
                "value": "/devices/%s/attributes/%s/value" % (device, attr),
                "info": "/devices/%s/attributes/%s/info" % (device, attr),
                "history": "/devices/%s/attributes/%s/history" % (device, attr),
                "properties": "/devices/%s/attributes/%s/properties" % (device,
                                                                        attr),
                "_links": {
                    "_device": "/devices/%s" % device,
                    "_parent": "/devices/%s/attributes/%s" % (device, attr),
                    "_self": "/devices/%s/attributes/%s/info" % (device, attr)
                }
            })

    data = json.dumps(results, cls=TangoEncoder, ensure_ascii=True)
    return Response(data, mimetype="application/json")


@tango.route('/devices/<domain>/<family>/<member>/attributes/<attribute>/info',
             methods=["GET", "PUT"])
def get_device_attribute_info(domain, family, member, attribute):
    "Return all config parameters about the attribute"
    device = "%s/%s/%s" % (domain, family, member)
    try:
        proxy = get_device_proxy(device)
    except PyTango.DevFailed as e:
        return make_error_response(e)

    attr_info = proxy.get_attribute_config(attribute)
    data = json.dumps(dict(
        data_format=str(attr_info.data_format),
        description=attr_info.description,
        display_unit=attr_info.display_unit,
        extensions=list(attr_info.extensions),
        format=attr_info.format,
        label=attr_info.label,
        level=str(attr_info.disp_level),
        max_alarm=attr_info.max_alarm,
        max_dim_x=attr_info.max_dim_x,
        max_dim_y=attr_info.max_dim_y,
        max_value=attr_info.max_value,
        name=attr_info.name,
        standard_unit=attr_info.standard_unit,
        unit=attr_info.unit,
        writable=str(attr_info.writable),
        writable_attr_name=attr_info.writable_attr_name
    ))
    return Response(data, mimetype="application/json")


@tango.route('/device/<domain>/<family>/<member>/attributes/<attribute>/info',
             methods=["PUT"])
def post_device_attribute_info(domain, family, member, attribute):
    "Change config parameters for an attribute"
    config = request.args
    device = "%s/%s/%s" % (domain, family, member)

    try:
        proxy = get_device_proxy(device)
    except PyTango.DeviceProxy as e:
        return jsonify(errors=str(e))

    try:
        info = proxy.get_attribute_config(attribute)
        for param, value in config.items():
            # some configs are numeric, most are strings
            if param in ("max_dim_x", "max_dim_y"):
                setattr(info, param, int(value))
            else:
                setattr(info, param, value)
        proxy.set_attribute_config(info)
        return jsonify(data={})
    except PyTango.DevFailed as e:
        return make_error_response(e)


@tango.route('/device/<domain>/<family>/<member>/attributes', methods=["GET"])
def get_device_attributes(domain, family, member):
    "Return the values of selected attributes"
    devname = "%s/%s/%s" % (domain, family, member)
    try:
        device = get_device_proxy(devname)
    except PyTango.DevFailed as e:
        return make_error_response(e)

    attrs = request.args
    if not attrs:
        attributes = list(device.get_attribute_list())
        return jsonify(result=["/device/%s/%s" % (devname, attr)
                               for attr in attributes])

    attributes, values = zip(*attrs.items())
    if not any(v != "" for v in values):
        results = device.read_attributes(attributes)
        data = {}
        for attr in results:
            data[attr.name] = {
                "value": attr.value,
                "quality": str(attr.quality),
                "timestamp": attr.time.totime()
            }
            if attr.w_value is not None:  # can w_value be set to None?
                data[attr.name]["w_value"] = attr.w_value
            if attr.has_failed:
                data[attr.name]["has_failed"] = True
        return jsonify(data=data)

    return jsonify(errors="...")


@tango.route('/devices/<domain>/<family>/<member>/attributes/<attribute>',
             methods=["GET", "PUT"])
def get_device_attribute(domain, family, member, attribute):
    device = "%s/%s/%s" % (domain, family, member)
    print device, attribute
    try:
        proxy = get_device_proxy(device)
    except PyTango.DevFailed as e:
        return make_error_response(e)

    if request.method == "PUT":
        str_value = request.args.get("value")
        if not str_value:
            return ""  # TODO!
        attr_info = proxy.get_attribute_config(attribute)
        value = str_2_obj(str_value, attr_info.data_type)
        if attr_info.writable in (PyTango.AttrWriteType.READ_WRITE,
                                  PyTango.AttrWriteType.READ_WITH_WRITE):
            # if possible, we write and read in one call...
            result = proxy.write_read_attribute(attribute, value)
        else:
            proxy.write_attribute(attribute, value)
            result = proxy.read_attribute(attribute)
    else:
        result = proxy.read_attribute(attribute)

    # TODO: this needs to be smarter
    if isinstance(result.value, PyTango._PyTango.DevState):
        value = str(result.value)
    else:
        value = result.value
    data = json.dumps(dict(name=result.name,
                           value=value, quality=str(result.quality),
                           timestamp=result.time.totime(), _links="..."))
    return Response(data, mimetype="application/json")


#### DEVICE PROPERTIES ####

def decode_device_properties(data):
    props = []
    n = int(data[1])
    pos = 2
    for i in range(n):
        prop = data[pos]
        length = int(data[pos+1])
        value = data[pos+2:pos+2+length]
        props.append({"name": prop, "values": value})
        pos = pos+2+length
    return props


def encode_device_properties(device, data):
    args = [device, str(len(data))]
    for prop, values in data.items():
        args.append(prop)
        args.append(str(len(values)))
        args.extend((str(v) for v in values))
    return args


@tango.route('/devices/<domain>/<family>/<member>/properties',
             methods=["GET", "PUT", "POST"])
def get_device_properties(domain, family, member):
    device = "%s/%s/%s" % (domain, family, member)
    args = request.args
    if request.method in ("PUT", "POST"):
        props = args.keys()
        data = {}
        for prop in props:
            value = args.getlist(prop)
            data[prop] = value
        db.DbPutDeviceProperty(encode_device_properties(device, data))
    else:
        wildcard = request.args.get("wildcard", "*")
        props = db.DbGetDevicePropertyList([device, wildcard])
    data = db.DbGetDeviceProperty([device] + props)
    if not data:
        return ""
    result = decode_device_properties(data)
    return Response(json.dumps(result), mimetype="application/json")


@tango.route('/devices/<domain>/<family>/<member>/properties/<prop>',
             methods=["GET", "PUT", "POST"])
def read_write_device_property(domain, family, member, prop):
    device = "%s/%s/%s" % (domain, family, member)
    args = request.args
    if request.method in ("PUT", "POST"):
        value = args.getlist("value")
        db.DbPutDeviceProperty([device, "1", prop, str(len(value))] + value)
    data = db.DbGetDeviceProperty([device, prop])
    result = decode_device_properties(data)
    return Response(json.dumps(result), mimetype="application/json")


### COMMANDS ###

@tango.route('/devices/<domain>/<family>/<member>/commands', methods=["GET"])
def get_device_commands(domain, family, member):
    device = "%s/%s/%s" % (domain, family, member)
    try:
        proxy = get_device_proxy(device)
    except PyTango.DevFailed as e:
        return make_error_response(e)
    cmd_infos = proxy.command_list_query()
    result = [{
        "name": info.cmd_name,
        "history": "/devices/%s/commands/%s/history" % (device, info.cmd_name),
        "info": {
            "level": str(info.disp_level),
            "cmd_tag": info.cmd_tag,
            "in_type": str(info.in_type),
            "out_type": str(info.out_type),
            "in_type_desc": info.in_type_desc,
            "out_type_desc": info.out_type_desc
        },
        "_links": {
            "_parent": "/devices/%s" % device,
            "_self": "/devices/%s/commands" % device
        }
    } for info in cmd_infos]
    return Response(json.dumps(result), mimetype="application/json")


