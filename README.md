## mtango-flask ##

This is a *work in progress* implementation of the TANGO "REST" interface.

See https://bitbucket.org/hzgwpn/mtango for API documentation. Note that this project was started with an early version of the standard and it's likely to be very out of date now.


### Requirements ###

flask, pytango


### Running ###

To start in a flask dev server, do:

    $ FLASK_APP=server.py flask run

Then you should be able to do e.g.
    
    $ http localhost:5000/rest/devices/sys/database/2/state
    HTTP/1.0 200 OK
    Content-Length: 243
    Content-Type: application/json
    Date: Mon, 20 Mar 2017 09:11:59 GMT
    Server: Werkzeug/0.12.1 Python/2.7.12

    {
        "_links": {
            "_parent": "/devices/sys/database/2", 
            "_self": "/devices/sys/database/2/state", 
            "_state": "/devices/sys/database/2/attributes/State", 
            "_status": "/devices/sys/database/2/attributes/Status"
        }, 
        "state": "ON", 
        "status": "Device is OK"
    }


### Notes ###
This does not use any flask REST addons like flask-restful or eve. Maybe that would be a good idea, but I have a feeling that it would not be so easy to implement the existing API specification using something like that. There would likely be various workarounds to get the behavior right, and then the point is sort of lost.
