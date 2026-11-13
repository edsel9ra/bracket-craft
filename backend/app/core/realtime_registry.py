from collections import UserDict


class SocketRegistry(UserDict):
    def __init__(self):
        self.organizations = {}
        super().__init__()

    def __setitem__(self, sid, metadata):
        if sid in self.data:
            del self[sid]
        self.data[sid] = metadata
        if metadata.get('scope') == 'organization':
            organization = str(metadata['organization_id'])
            principal = (metadata.get('user_id'), metadata.get('session_id'))
            self.organizations.setdefault(organization, {}).setdefault(principal, set()).add(sid)

    def __delitem__(self, sid):
        metadata = self.data.pop(sid)
        if metadata.get('scope') == 'organization':
            organization = str(metadata['organization_id'])
            principal = (metadata.get('user_id'), metadata.get('session_id'))
            principals = self.organizations[organization]
            sockets = principals[principal]
            sockets.remove(sid)
            if not sockets:
                del principals[principal]
            if not principals:
                del self.organizations[organization]

    def organization_sessions(self, organization_id):
        return {sid: self.data[sid] for sockets in self.organizations.get(str(organization_id), {}).values()
                for sid in sockets}
