# -*- coding: utf-8 -*-
#
# vim: expandtab shiftwidth=4 softtabstop=4
#
"""ownCloud client module

Makes it possible to access files on a remote ownCloud instance,
share them or access application attributes.
"""

import datetime
import time
import urllib
import urlparse
import requests
import xml.etree.ElementTree as ET
import os


class ResponseError(Exception):
    def __init__(self, res):
        if type(res) is int:
            code = res
        else:
            code = res.status_code
            self.res = res
        Exception.__init__(self, "HTTP error: %i" % code)
        self.status_code = code

    def get_resource_body(self):
        if None != self.res:
            return self.res.text
        else:
            return None

class PublicShare():
    """Public share information"""

    def __init__(self, share_id, target_file, link, token):
        self.share_id = share_id
        self.target_file = target_file
        self.link = link
        self.token = token

    def __str__(self):
        return 'PublicShare(id=%i,path=%s,link=%s,token=%s)' % \
               (self.share_id, self.target_file, self.link, self.token)


class UserShare():
    """User share information"""

    def __init__(self, share_id, share, perms):
        self.share_id = share_id
        self.share = share
        self.perms = perms

    def __str__(self):
        return "UserShare(id=%i,path='%s',perms=%s)" % \
               (self.share_id, self.share, self.perms)


class GroupShare():
    """Group share information"""

    def __init__(self, share_id, share, perms):
        self.share_id = share_id
        self.share = share
        self.perms = perms

    def __str__(self):
        return "GroupShare(id=%i,path='%s',perms=%s)" % \
               (self.share_id, self.share, self.perms)


class FileInfo():
    """File information"""

    __DATE_FORMAT = '%a, %d %b %Y %H:%M:%S %Z'

    def __init__(self, path, file_type='file', attributes=None):
        self.path = path
        if path[-1] == '/':
            path = path[0:-1]
        self.name = os.path.basename(path)
        self.file_type = file_type
        self.attributes = attributes or {}

    def get_name(self):
        """Returns the base name of the file without path

        :returns: name of the file
        """
        return self.name

    def get_path(self):
        """Returns the full path to the file without name and without
        trailing slash

        :returns: path to the file
        """
        return os.path.dirname(self.path)

    def get_size(self):
        """Returns the size of the file or directory

        :returns: size of the file or directory
        """
        if self.attributes.has_key('{DAV:}getcontentlength'):
            return int(self.attributes['{DAV:}getcontentlength'])
        elif self.attributes.has_key('{http://owncloud.org/ns}size'):
            return int(self.attributes['{http://owncloud.org/ns}size'])
        return None

    def get_etag(self):
        """Returns the file etag

        :returns: file etag
        """
        return self.attributes['{DAV:}getetag']

    def get_content_type(self):
        """Returns the file content type

        :returns: file content type
        """
        if self.attributes.has_key('{DAV:}getcontenttype'):
            return self.attributes['{DAV:}getcontenttype']

        if self.is_dir():
            return 'httpd/unix-directory'

        return None

    def get_last_modified(self):
        """Returns the last modified time

        :returns: last modified time
        :rtype: datetime object
        """
        return datetime.datetime.strptime(
            self.attributes['{DAV:}getlastmodified'],
            self.__DATE_FORMAT
        )

    def is_dir(self):
        """Returns whether the file info is a directory

        :returns: True if it is a directory, False otherwise
        """
        return self.file_type != 'file'

    def __str__(self):
        return 'File(path=%s,file_type=%s,attributes=%s)' % \
               (self.path, self.file_type, self.attributes)

    def __repr__(self):
        return self.__str__()


class Client():
    """ownCloud client"""

    OCS_SERVICE_SHARE = 'apps/files_sharing/api/v1'
    OCS_SERVICE_PRIVATEDATA = 'privatedata'
    OCS_SERVICE_CLOUD = 'cloud'

    # constants from lib/public/constants.php
    OCS_PERMISSION_READ = 1
    OCS_PERMISSION_UPDATE = 2
    OCS_PERMISSION_CREATE = 4
    OCS_PERMISSION_DELETE = 8
    OCS_PERMISSION_SHARE = 16
    OCS_PERMISSION_ALL = 31
    # constants from lib/public/share.php
    OCS_SHARE_TYPE_USER = 0
    OCS_SHARE_TYPE_GROUP = 1
    OCS_SHARE_TYPE_LINK = 3

    def __init__(self, url, **kwargs):
        """Instantiates a client

        :param url: URL of the target ownCloud instance
        :param verify_certs: True (default) to verify SSL certificates, False otherwise
        :param single_session: True to use a single session for every call
            (default, recommended), False to reauthenticate every call (use with ownCloud 5)
        :param debug: set to True to print debugging messages to stdout, defaults to False
        """
        if not url[-1] == '/':
            url += '/'

        self.url = url
        self.__session = None
        self.__debug = kwargs.get('debug', False)
        self.__verify_certs = kwargs.get('verify_certs', True)
        self.__single_session = kwargs.get('single_session', True)

        url_components = urlparse.urlparse(url)
        self.__davpath = url_components.path + 'remote.php/webdav'
        self.__webdav_url = url + 'remote.php/webdav'

    def login(self, user_id, password):
        """Authenticate to ownCloud.
        This will create a session on the server.

        :param user_id: user id
        :param password: password
        :raises: ResponseError in case an HTTP error status was returned
        """

        self.__session = requests.session()
        self.__session.verify = self.__verify_certs
        self.__session.auth = (user_id, password)
        # TODO: use another path to prevent that the server renders the file list page
        res = self.__session.get(self.url + 'index.php')
        if res.status_code == 200:
            if self.__single_session:
                # Keep the same session, no need to re-auth every call
                self.__session.auth = None
            return
        self.__session.close()
        self.__session = None
        raise ResponseError(res)

    def logout(self):
        """Log out the authenticated user and close the session.

        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        # TODO actual logout ?
        self.__session.close()
        return True

    def file_info(self, path):
        """Returns the file info for the given remote file

        :param path: path to the remote file
        :returns: file info
        :rtype: :class:`FileInfo` object or `None` if file
            was not found
        :raises: ResponseError in case an HTTP error status was returned
        """
        res = self.__make_dav_request('PROPFIND', path)
        if res:
            return res[0]
        return None

    def list(self, path):
        """Returns the listing/contents of the given remote directory

        :param path: path to the remote directory
        :returns: directory listing
        :rtype: array of :class:`FileInfo` objects
        :raises: ResponseError in case an HTTP error status was returned
        """
        if not path[-1] == '/':
            path += '/'
        res = self.__make_dav_request('PROPFIND', path)
        # first one is always the root, remove it from listing
        if res:
            return res[1:]
        return None

    def get_file_contents(self, path):
        """Returns the contents of a remote file

        :param path: path to the remote file
        :returns: file contents
        :rtype: binary data
        :raises: ResponseError in case an HTTP error status was returned
        """
        path = self.__normalize_path(path)
        res = self.__session.get(self.__webdav_url + path)
        if res.status_code == 200:
            return res.content
        return False

    def get_file(self, remote_path, local_file=None):
        """Downloads a remote file

        :param remote_path: path to the remote file
        :param local_file: optional path to the local file. If none specified,
            the file will be downloaded into the current directory
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        remote_path = self.__normalize_path(remote_path)
        res = self.__session.get(
            self.__webdav_url + remote_path,
            stream=True
        )
        if res.status_code == 200:
            if local_file is None:
                # use downloaded file name from Content-Disposition
                # local_file = res.headers['content-disposition']
                local_file = os.path.basename(remote_path)

            file_handle = open(local_file, 'wb', 8192)
            for chunk in res.iter_content(8192):
                file_handle.write(chunk)
            file_handle.close()
            return True
        return False

    def get_directory_as_zip(self, remote_path, local_file):
        """Downloads a remote directory as zip

        :param remote_path: path to the remote directory to download
        :param local_file: path and name of the target local file
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        remote_path = self.__normalize_path(remote_path)
        url = self.url + 'index.php/apps/files/ajax/download.php?dir=' \
                + urllib.quote(remote_path)
        res = self.__session.get(url, stream=True)
        if res.status_code == 200:
            if local_file is None:
                # use downloaded file name from Content-Disposition
                # targetFile = res.headers['content-disposition']
                local_file = os.path.basename(remote_path)

            file_handle = open(local_file, 'wb', 8192)
            for chunk in res.iter_content(8192):
                file_handle.write(chunk)
            file_handle.close()
            return True
        return False

    def put_file_contents(self, remote_path, data):
        """Write data into a remote file

        :param remote_path: path of the remote file
        :param data: data to write into the remote file
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        return self.__make_dav_request('PUT', remote_path, data=data)

    def put_file(self, remote_path, local_source_file, **kwargs):
        """Upload a file

        :param remote_path: path to the target file. A target directory can
            also be specified instead by appending a "/"
        :param local_source_file: path to the local file to upload
        :param chunked: (optional) use file chunking (defaults to True)
        :param chunk_size: (optional) chunk size in bytes, defaults to 10 MB
        :param keep_mtime: (optional) also update the remote file to the same
            mtime as the local one, defaults to True
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        if kwargs.get('chunked', True):
            return self.__put_file_chunked(
                remote_path,
                local_source_file,
                **kwargs
            )

        stat_result = os.stat(local_source_file)

        headers = {}
        if kwargs.get('keep_mtime', True):
            headers['X-OC-MTIME'] = stat_result.st_mtime

        if remote_path[-1] == '/':
            remote_path += os.path.basename(local_source_file)
        file_handle = open(local_source_file, 'rb', 8192)
        res = self.__make_dav_request(
            'PUT',
            remote_path,
            data=file_handle,
            headers=headers
        )
        file_handle.close()
        return res

    def put_directory(self, target_path, local_directory, **kwargs):
        """Upload a directory with all its contents

        :param target_path: path of the directory to upload into
        :param local_directory: path to the local directory to upload
        :param \*\*kwargs: optional arguments that ``put_file`` accepts
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        target_path = self.__normalize_path(target_path)
        if not target_path[-1] == '/':
            target_path += '/'
        gathered_files = []

        if not local_directory[-1] == '/':
            local_directory += '/'

        basedir = os.path.basename(local_directory[0:-1]) + '/'
        # gather files to upload
        for path, _, files in os.walk(local_directory):
            gathered_files.append(
                (path, basedir + path[len(local_directory):], files)
            )

        for path, remote_path, files in gathered_files:
            self.mkdir(target_path + remote_path + '/')
            for name in files:
                if not self.put_file(target_path + remote_path + '/', path + '/' + name, **kwargs):
                    return False
        return True

    def __put_file_chunked(self, remote_path, local_source_file, **kwargs):
        """Uploads a file using chunks. If the file is smaller than
        ``chunk_size`` it will be uploaded directly.

        :param remote_path: path to the target file. A target directory can
        also be specified instead by appending a "/"
        :param local_source_file: path to the local file to upload
        :param \*\*kwargs: optional arguments that ``put_file`` accepts
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        chunk_size = kwargs.get('chunk_size', 10 * 1024 * 1024)
        result = True
        transfer_id = int(time.time())

        remote_path = self.__normalize_path(remote_path)
        if remote_path[-1] == '/':
            remote_path += os.path.basename(local_source_file)

        stat_result = os.stat(local_source_file)

        file_handle = open(local_source_file, 'rb', 8192)
        file_handle.seek(0, os.SEEK_END)
        size = file_handle.tell()
        file_handle.seek(0)

        headers = {}
        if kwargs.get('keep_mtime', True):
            headers['X-OC-MTIME'] = stat_result.st_mtime

        if size == 0:
            return self.__make_dav_request(
                'PUT',
                remote_path,
                data='',
                headers=headers
            )

        chunk_count = size / chunk_size

        if size % chunk_size > 0:
            chunk_count += 1

        if chunk_count > 1:
            headers['OC-CHUNKED'] = 1

        for chunk_index in range(0, chunk_count):
            data = file_handle.read(chunk_size)
            if chunk_count > 1:
                chunk_name = '%s-chunking-%s-%i-%i' % \
                             (remote_path, transfer_id, chunk_count, chunk_index)
            else:
                chunk_name = remote_path

            if not self.__make_dav_request(
                    'PUT',
                    chunk_name,
                    data=data,
                    headers=headers
            ):
                result = False
                break

        file_handle.close()
        return result

    def mkdir(self, path):
        """Creates a remote directory

        :param path: path to the remote directory to create
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        if not path[-1] == '/':
            path += '/'
        return self.__make_dav_request('MKCOL', path)

    def delete(self, path):
        """Deletes a remote file or directory

        :param path: path to the file or directory to delete
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        return self.__make_dav_request('DELETE', path)

    def delete_share(self, share_id):
        """Unshares a file or directory

        :param share_id: Share ID (int)
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        if not isinstance(share_id, int):
            return False

        res = self.__make_ocs_request(
            'DELETE',
            self.OCS_SERVICE_SHARE,
            'shares/' + str(share_id)
        )
        if res.status_code == 200:
            return res
        raise ResponseError(res)

    def update_share(self, share_id, **kwargs):
        """Updates a given share

        :param share_id: (int) Share ID
        :param perms: (int) update permissions (see share_file_with_user() below)
        :param password: (string) updated password for public link Share
        :param public_upload: (boolean) enable/disable public upload for public shares
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """

        perms = kwargs.get('perms', None)
        password = kwargs.get('password', None)
        public_upload = kwargs.get('public_upload', None)
        if (isinstance(perms, int)) and (perms > self.OCS_PERMISSION_ALL):
            perms = None
        if not (perms or password or (public_upload is not None)):
            return False
        if not isinstance(share_id, int):
            return False

        data = {}
        if perms:
            data['permissions'] = perms
        if isinstance(password, basestring):
            data['password'] = password
        if (public_upload is not None) and (isinstance(public_upload, bool)):
            data['publicUpload'] = str(public_upload).lower()

        res = self.__make_ocs_request(
            'PUT',
            self.OCS_SERVICE_SHARE,
            'shares/' + str(share_id),
            data=data
        )
        if res.status_code == 200:
            return True
        raise ResponseError(res)

    def move(self, remote_path_source, remote_path_target):
        """Deletes a remote file or directory

        :param remote_path_source: source file or folder to move
        :param remote_path_target: target file to which to move
        the source file. A target directory can also be specified
        instead by appending a "/"
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        if remote_path_target[-1] == '/':
            remote_path_target += os.path.basename(remote_path_source)

        if not (remote_path_target[0] == '/'):
            remote_path_target = '/' + remote_path_target

        remote_path_source = self.__normalize_path(remote_path_source)
        headers = {
            'Destination': self.__webdav_url + urllib.quote(self.__encode_string(remote_path_target))
        }

        return self.__make_dav_request(
            'MOVE',
            remote_path_source,
            headers=headers
        )

    def share_file_with_link(self, path):
        """Shares a remote file with link

        :param path: path to the remote file to share
        :returns: instance of :class:`PublicShare` with the share info
            or False if the operation failed
        :raises: ResponseError in case an HTTP error status was returned
        """
        path = self.__normalize_path(path)
        post_data = {
            'shareType': self.OCS_SHARE_TYPE_LINK,
            'path': self.__encode_string(path)
        }

        res = self.__make_ocs_request(
            'POST',
            self.OCS_SERVICE_SHARE,
            'shares',
            data=post_data
        )
        if res.status_code == 200:
            tree = ET.fromstring(res.content)
            self.__check_ocs_status(tree)
            data_el = tree.find('data')
            return PublicShare(
                int(data_el.find('id').text),
                path,
                data_el.find('url').text,
                data_el.find('token').text
            )
        raise ResponseError(res)

    def is_shared(self, path):
        """Checks whether a path is already shared

        :param path: path to the share to be checked
        :returns: True if the path is already shared, else False
        :raises: ResponseError in case an HTTP error status was returned
        """
        # make sure that the path exist - if not, raise ResponseError
        self.file_info(path)
        try:
            result = self.get_shares(path)
            if result:
                return len(result) > 0
        except ResponseError as e:
            if e.status_code != 404:
                raise e
            return False
        return False

    def get_shares(self, path='', **kwargs):
        """Returns array of shares

        :param path: path to the share to be checked
        :param reshares: (optional, boolean) returns not only the shares from
            the current user but all shares from the given file (default: False)
        :param subfiles: (optional, boolean) returns all shares within
            a folder, given that path defines a folder (default: False)
        :returns: array of shares or empty array if the operation failed
        :raises: ResponseError in case an HTTP error status was returned
        """
        if not (isinstance(path, basestring)):
            return None

        data = 'shares'
        if path != '':
            data += '?'
            path = self.__encode_string(self.__normalize_path(path))
            args = {'path': path}
            reshares = kwargs.get('reshares', False)
            if isinstance(reshares, bool) and reshares:
                args['reshares'] = reshares
            subfiles = kwargs.get('subfiles', False)
            if isinstance(subfiles, bool) and subfiles:
                args['subfiles'] = subfiles
            data += urllib.urlencode(args)

        res = self.__make_ocs_request(
            'GET',
            self.OCS_SERVICE_SHARE,
            data
        )
        if res.status_code == 200:
            tree = ET.fromstring(res.content)
            self.__check_ocs_status(tree)
            shares = []
            for element in tree.find('data').iter('element'):
                share_attr = {}
                for child in element:
                    key = child.tag
                    value = child.text
                    share_attr[key] = value
                shares.append(share_attr)
            if len(shares) > 0:
                return shares
        raise ResponseError(res)

    def create_user(self, user_name, initial_password):
        """Create a new user with an initial password via provisioning API.
        It is not an error, if the user already existed before.
        If you get back an error 999, then the provisioning API is not enabled.

        :param user_name:  name of user to be created
        :param initial_password:  password for user being created
        :returns: True on success
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request(
            'POST',
            self.OCS_SERVICE_CLOUD,
            'users',
            data={'password': initial_password, 'userid': user_name}
        )

        # We get 200 when the user was just created.
        if res.status_code == 200:
            # We get an inner 102 although we have an outer 200 when the user already exists.
            tree = ET.fromstring(res.text)
            self.__check_ocs_status(tree, [100, 102])
            return True

        raise ResponseError(res)

    def delete_user(self, user_name):
        """Deletes a user via provisioning API.
        If you get back an error 999, then the provisioning API is not enabled.

        :param user_name:  name of user to be deleted
        :returns: True on success
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request(
            'DELETE',
            self.OCS_SERVICE_CLOUD,
            'users/' + user_name
        )

        # We get 200 when the user was deleted.
        if res.status_code == 200:
            return True

        raise ResponseError(res)

    def user_exists(self, user_name):
        """Checks a user via provisioning API.
        If you get back an error 999, then the provisioning API is not enabled.

        :param user_name:  name of user to be checked
        :returns: True if user found
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request(
            'GET',
            self.OCS_SERVICE_CLOUD,
            'users?search=' + user_name
        )

        if res.status_code == 200:
            tree = ET.fromstring(res.text)
            code_el = tree.find('data/users/element')

            if code_el is not None and code_el.text == user_name:
                return True
            else:
                return False

        raise ResponseError(res)

    def add_user_to_group(self, user_name, group_name):
        """Adds a user to a group.

        :param user_name:  name of user to be added
        :param group_name:  name of group user is to be added to
        :returns: True if user added
        :raises: ResponseError in case an HTTP error status was returned

        """

        res = self.__make_ocs_request(
            'POST',
            self.OCS_SERVICE_CLOUD,
            'users/' + user_name + '/groups',
            data={'groupid': group_name}
        )

        if res.status_code == 200:
            tree = ET.fromstring(res.text)
            self.__check_ocs_status(tree, [100, 102])
            return True

        raise ResponseError(res)

    def remove_user_from_group(self, user_name, group_name):
        """Removes a user from a group.

        :param user_name:  name of user to be removed
        :param group_name:  name of group user is to be removed from
        :returns: True if user removed
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request(
            'DELETE',
            self.OCS_SERVICE_CLOUD,
            'users/' + user_name + '/groups',
            data={'groupid': group_name}
        )

        if res.status_code == 200:
            tree = ET.fromstring(res.text)
            self.__check_ocs_status(tree, [100, 102])
            return True

        raise ResponseError(res)

    def share_file_with_user(self, path, user, **kwargs):
        """Shares a remote file with specified user

        :param path: path to the remote file to share
        :param user: name of the user whom we want to share a file/folder
        :param perms (optional): permissions of the shared object
            defaults to read only (1)
            http://doc.owncloud.org/server/6.0/admin_manual/sharing_api/index.html
        :returns: instance of :class:`UserShare` with the share info
            or False if the operation failed
        :raises: ResponseError in case an HTTP error status was returned
        """
        perms = kwargs.get('perms', self.OCS_PERMISSION_READ)
        if (((not isinstance(perms, int)) or (perms > self.OCS_PERMISSION_ALL))
                or ((not isinstance(user, basestring)) or (user == ''))):
            return False

        path = self.__normalize_path(path)
        post_data = {
            'shareType': self.OCS_SHARE_TYPE_USER,
            'shareWith': user,
            'path': self.__encode_string(path),
            'permissions': perms
        }

        res = self.__make_ocs_request(
            'POST',
            self.OCS_SERVICE_SHARE,
            'shares',
            data=post_data
        )

        if self.__debug:
            print(
                'OCS share_file request for file %s with permissions %i returned: %i' % (path, perms, res.status_code))
        if res.status_code == 200:
            tree = ET.fromstring(res.content)
            self.__check_ocs_status(tree)
            data_el = tree.find('data')
            return UserShare(
                int(data_el.find('id').text),
                path,
                perms
            )
        raise ResponseError(res)

    def create_group(self, group_name):
        """Create a new group via provisioning API.
        If you get back an error 999, then the provisioning API is not enabled.

        :param group_name:  name of group to be created
        :returns: True if group created
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request(
            'POST',
            self.OCS_SERVICE_CLOUD,
            'groups',
            data={'groupid': group_name}
        )

        # We get 200 when the group was just created.
        if res.status_code == 200:
            # We get an inner 102 although we have an outer 200 when the group already exists.
            tree = ET.fromstring(res.text)
            self.__check_ocs_status(tree, [100, 102])
            return True

        raise ResponseError(res)

    def delete_group(self, group_name):
        """Delete a group via provisioning API.
        If you get back an error 999, then the provisioning API is not enabled.

        :param group_name:  name of group to be deleted
        :returns: True if group deleted
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request(
            'DELETE',
            self.OCS_SERVICE_CLOUD,
            'groups/' + group_name
        )

        # We get 200 when the group was just deleted.
        if res.status_code == 200:
            return True

        raise ResponseError(res)

    def group_exists(self, group_name):
        """Checks a group via provisioning API.
        If you get back an error 999, then the provisioning API is not enabled.

        :param group_name:  name of group to be checked
        :returns: True if group exists
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request(
            'GET',
            self.OCS_SERVICE_CLOUD,
            'groups?search=' + group_name
        )

        if res.status_code == 200:
            tree = ET.fromstring(res.text)
            code_el = tree.find('data/groups/element')

            if code_el is not None and code_el.text == group_name:
                return True
            else:
                return False

        raise ResponseError(res)

    def share_file_with_group(self, path, group, **kwargs):
        """Shares a remote file with specified group

        :param path: path to the remote file to share
        :param user: name of the user whom we want to share a file/folder
        :param perms (optional): permissions of the shared object
            defaults to read only (1)
            http://doc.owncloud.org/server/6.0/admin_manual/sharing_api/index.html
        :returns: instance of :class:`GroupShare` with the share info
            or False if the operation failed
        :raises: ResponseError in case an HTTP error status was returned
        """
        perms = kwargs.get('perms', self.OCS_PERMISSION_READ)
        if (((not isinstance(perms, int)) or (perms > self.OCS_PERMISSION_ALL))
                or ((not isinstance(group, basestring)) or (group == ''))):
            return False

        path = self.__normalize_path(path)
        post_data = {'shareType': self.OCS_SHARE_TYPE_GROUP, 'shareWith': group, 'path': path, 'permissions': perms}

        res = self.__make_ocs_request(
            'POST',
            self.OCS_SERVICE_SHARE,
            'shares',
            data=post_data
        )
        if res.status_code == 200:
            tree = ET.fromstring(res.text)
            self.__check_ocs_status(tree)
            data_el = tree.find('data')
            return GroupShare(
                int(data_el.find('id').text),
                path,
                perms
            )
        raise ResponseError(res)

    def get_config(self):
        """Returns ownCloud config information
        :returns: array of tuples (key, value) for each information
            e.g. [('version', '1.7'), ('website', 'ownCloud'), ('host', 'cloud.example.com'),
            ('contact', ''), ('ssl', 'false')]
        :raises: ResponseError in case an HTTP error status was returned
        """
        path = 'config'
        res = self.__make_ocs_request(
            'GET',
            '',
            path
        )
        if res.status_code == 200:
            tree = ET.fromstring(res.content)
            self.__check_ocs_status(tree)
            values = []

            element = tree.find('data')
            if element is not None:
                keys = ['version', 'website', 'host', 'contact', 'ssl']
                for key in keys:
                    text = element.find(key).text or ''
                    values.append(text)
                return zip(keys, values)
            else:
                return None
        raise ResponseError(res)

    def get_attribute(self, app=None, key=None):
        """Returns an application attribute

        :param app: application id
        :param key: attribute key or None to retrieve all values for the
            given application
        :returns: attribute value if key was specified, or an array of tuples
            (key, value) for each attribute
        :raises: ResponseError in case an HTTP error status was returned
        """
        path = 'getattribute'
        if app is not None:
            path += '/' + urllib.quote(app, '')
            if key is not None:
                path += '/' + urllib.quote(self.__encode_string(key), '')
        res = self.__make_ocs_request(
            'GET',
            self.OCS_SERVICE_PRIVATEDATA,
            path
        )
        if res.status_code == 200:
            tree = ET.fromstring(res.content)
            self.__check_ocs_status(tree)
            values = []
            for element in tree.find('data').iter('element'):
                app_text = element.find('app').text
                key_text = element.find('key').text
                value_text = element.find('value').text or ''
                if key is None:
                    if app is None:
                        values.append((app_text, key_text, value_text))
                    else:
                        values.append((key_text, value_text))
                else:
                    return value_text

            if len(values) == 0 and key is not None:
                return None
            return values
        raise ResponseError(res)

    def set_attribute(self, app, key, value):
        """Sets an application attribute

        :param app: application id
        :param key: key of the attribute to set
        :param value: value to set
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        path = 'setattribute/' + urllib.quote(app, '') + '/' + urllib.quote(self.__encode_string(key), '')
        res = self.__make_ocs_request(
            'POST',
            self.OCS_SERVICE_PRIVATEDATA,
            path,
            data={'value': self.__encode_string(value)}
        )
        if res.status_code == 200:
            tree = ET.fromstring(res.content)
            self.__check_ocs_status(tree)
            return True
        raise ResponseError(res)

    def delete_attribute(self, app, key):
        """Deletes an application attribute

        :param app: application id
        :param key: key of the attribute to delete
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned
        """
        path = 'deleteattribute/' + urllib.quote(app, '') + '/' + urllib.quote(self.__encode_string(key), '')
        res = self.__make_ocs_request(
            'POST',
            self.OCS_SERVICE_PRIVATEDATA,
            path
        )
        if res.status_code == 200:
            tree = ET.fromstring(res.content)
            self.__check_ocs_status(tree)
            return True
        raise ResponseError(res)

    def get_apps(self):
        """ List all enabled apps through the provisioning api.

        :returns: a dict of apps, with values True/False, representing the enabled state.
        :raises: ResponseError in case an HTTP error status was returned
        """
        ena_apps = {}

        res = self.__make_ocs_request('GET', self.OCS_SERVICE_CLOUD, 'apps')
        if res.status_code != 200:
            raise ResponseError(res)
        tree = ET.fromstring(res.text)
        self.__check_ocs_status(tree)
        # <data><apps><element>files</element><element>activity</element> ...
        for el in tree.findall('data/apps/element'):
            ena_apps[el.text] = False

        res = self.__make_ocs_request('GET', self.OCS_SERVICE_CLOUD, 'apps?filter=enabled')
        if res.status_code != 200:
            raise ResponseError(res)
        tree = ET.fromstring(res.text)
        self.__check_ocs_status(tree)
        for el in tree.findall('data/apps/element'):
            ena_apps[el.text] = True

        return ena_apps

    def enable_app(self, appname):
        """Enable an app through provisioning_api

        :param appname:  Name of app to be enabled
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request('POST', self.OCS_SERVICE_CLOUD, 'apps/' + appname)
        if res.status_code == 200:
            return True

        raise ResponseError(res)

    def disable_app(self, appname):
        """Disable an app through provisioning_api

        :param appname:  Name of app to be disabled
        :returns: True if the operation succeeded, False otherwise
        :raises: ResponseError in case an HTTP error status was returned

        """
        res = self.__make_ocs_request('DELETE', self.OCS_SERVICE_CLOUD, 'apps/' + appname)
        if res.status_code == 200:
            return True

        raise ResponseError(res)

    @staticmethod
    def __normalize_path(path):
        """Makes sure the path starts with a "/"
        """
        if isinstance(path, FileInfo):
            path = path.path
        if len(path) == 0:
            return '/'
        if path[0] != '/':
            path = '/' + path
        return path

    @staticmethod
    def __encode_string(s):
        """Encodes a unicode instance to utf-8. If a str is passed it will
        simply be returned

        :param s: str or unicode to encode
        :returns: encoded output as str
        """
        if isinstance(s, unicode):
            return s.encode('utf-8')
        return s

    @staticmethod
    def __check_ocs_status(tree, accepted_codes=[100]):
        """Checks the status code of an OCS request

        :param tree: response parsed with elementtree
        :param accepted_codes: list of statuscodes we consider good. E.g. [100,102] can be used to accept a POST
               returning an 'already exists' condition
        :raises: ResponseError if the http status is not 200, or the webdav status is not one of the accepted_codes.
        """
        code_el = tree.find('meta/statuscode')
        if code_el is not None and int(code_el.text) not in accepted_codes:
            r = requests.Response()
            msg_el = tree.find('meta/message')
            if msg_el is None:
                msg_el = tree  # fallback to the entire ocs response, if we find no message.
            r._content = ET.tostring(msg_el)
            r.status_code = int(code_el.text)
            raise ResponseError(r)

    def __make_ocs_request(self, method, service, action, **kwargs):
        """Makes a OCS API request

        :param method: HTTP method
        :param service: service name
        :param action: action path
        :param \*\*kwargs: optional arguments that ``requests.Request.request`` accepts
        :returns :class:`requests.Response` instance
        """
        slash = ''
        if service:
            slash = '/'
        path = 'ocs/v1.php/' + service + slash + action
        if self.__debug:
            print('OCS request: %s %s' % (method, self.url + path))

        attributes = kwargs.copy()

        if not attributes.has_key('headers'):
            attributes['headers'] = {}

        attributes['headers']['OCS-APIREQUEST'] = 'true'

        res = self.__session.request(method, self.url + path, **attributes)
        return res

    def __make_dav_request(self, method, path, **kwargs):
        """Makes a WebDAV request

        :param method: HTTP method
        :param path: remote path of the targetted file
        :param \*\*kwargs: optional arguments that ``requests.Request.request`` accepts
        :returns array of :class:`FileInfo` if the response
        contains it, or True if the operation succeded, False
        if it didn't
        """
        if self.__debug:
            print('DAV request: %s %s' % (method, path))
            if kwargs.get('headers'):
                print('Headers: ', kwargs.get('headers'))

        path = self.__normalize_path(path)
        res = self.__session.request(
            method,
            self.__webdav_url + urllib.quote(self.__encode_string(path)),
            **kwargs
        )
        if self.__debug:
            print('DAV status: %i' % res.status_code)
        if res.status_code == 200 or res.status_code == 207:
            return self.__parse_dav_response(res)
        if res.status_code == 204 or res.status_code == 201:
            return True
        raise ResponseError(res)

    def __parse_dav_response(self, res):
        """Parses the DAV responses from a multi-status response

        :param res: DAV response
        :returns array of :class:`FileInfo` or False if
        the operation did not succeed
        """
        if res.status_code == 207:
            tree = ET.fromstring(res.content)
            items = []
            for child in tree:
                items.append(self.__parse_dav_element(child))
            return items
        return False

    def __parse_dav_element(self, dav_response):
        """Parses a single DAV element

        :param dav_response: DAV response
        :returns :class:`FileInfo`
        """
        href = urllib.unquote(
            self.__strip_dav_path(dav_response.find('{DAV:}href').text)
        ).decode('utf-8')
        file_type = 'file'
        if href[-1] == '/':
            file_type = 'dir'

        file_attrs = {}
        attrs = dav_response.find('{DAV:}propstat')
        attrs = attrs.find('{DAV:}prop')
        for attr in attrs:
            file_attrs[attr.tag] = attr.text

        return FileInfo(href, file_type, file_attrs)

    def __strip_dav_path(self, path):
        """Removes the leading "remote.php/webdav" path from the given path

        :param path: path containing the remote DAV path "remote.php/webdav"
        :returns: path stripped of the remote DAV path
        """
        if path.startswith(self.__davpath):
            return path[len(self.__davpath):]
        return path
