## mtango-flask ##
This is a *work in progress* implementation of the TANGO "REST" interface, and it's also not up to date with the standard. It should not be used in its current form!

See https://bitbucket.org/hzgwpn/mtango for API documentation.

Requirements: flask, pytango

### Notes ###
This does not use any flask REST addons like flask-restful or eve. Maybe that would be a good idea, but I have a feeling that it would not be so easy to implement the existing API specification using something like that. There would likely be various workarounds to get the behavior right, and then the point is sort of lost.
