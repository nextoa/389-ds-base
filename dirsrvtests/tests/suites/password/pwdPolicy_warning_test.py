# --- BEGIN COPYRIGHT BLOCK ---
# Copyright (C) 2016 Red Hat, Inc.
# All rights reserved.
#
# License: GPL (version 3 or any later version).
# See LICENSE for details.
# --- END COPYRIGHT BLOCK ---
#
import pytest
import subprocess
from ldap.controls.ppolicy import PasswordPolicyControl
from lib389.tasks import *
from lib389.utils import *
from lib389.topologies import topology_st

from lib389._constants import (DEFAULT_SUFFIX, DN_CONFIG, PASSWORD, DN_DM,
                               HOST_STANDALONE, PORT_STANDALONE, SERVERID_STANDALONE)
from dateutil.parser import parse as dt_parse
import datetime

CONFIG_ATTR = 'passwordSendExpiringTime'
USER_DN = 'uid=tuser,{}'.format(DEFAULT_SUFFIX)
USER_PASSWD = b'secret123'

logging.getLogger(__name__).setLevel(logging.INFO)
log = logging.getLogger(__name__)


@pytest.fixture
def global_policy(topology_st, request):
    """Sets the required global
    password policy attributes under
    cn=config entry
    """

    attrs = {'passwordExp': '',
             'passwordMaxAge': '',
             'passwordWarning': '',
             CONFIG_ATTR: ''}

    log.info('Get the default values')
    entry = topology_st.standalone.getEntry(DN_CONFIG, ldap.SCOPE_BASE,
                                            '(objectClass=*)', attrs.keys())

    for key in attrs.keys():
        attrs[key] = entry.getValue(key)

    log.info('Set the new values')
    topology_st.standalone.config.replace_many(('passwordExp', 'on'),
                                               ('passwordMaxAge', '172800'),
                                               ('passwordWarning', '86400'),
                                               (CONFIG_ATTR, 'on'))
    def fin():
        """Resets the defaults"""

        log.info('Reset the defaults')
        for key in attrs.keys():
            topology_st.standalone.modify_s(DN_CONFIG, [
                (ldap.MOD_REPLACE, key, ensure_bytes(attrs[key]))])

    request.addfinalizer(fin)
    # A short sleep is required after the modifying password policy or cn=config
    time.sleep(0.5)


@pytest.fixture
def global_policy_default(topology_st, request):
    """Sets the required global password policy
    attributes for testing the default behavior
    of password expiry warning time
    """

    attrs = {'passwordExp': '',
             'passwordMaxAge': '',
             'passwordWarning': '',
             CONFIG_ATTR: ''}

    log.info('Get the default values')
    entry = topology_st.standalone.getEntry(DN_CONFIG, ldap.SCOPE_BASE,
                                            '(objectClass=*)', attrs.keys())
    for key in attrs.keys():
        attrs[key] = entry.getValue(key)

    log.info('Set the new values')
    topology_st.standalone.modify_s(DN_CONFIG, [
        (ldap.MOD_REPLACE, 'passwordExp', b'on'),
        (ldap.MOD_REPLACE, 'passwordMaxAge', b'8640000'),
        (ldap.MOD_REPLACE, 'passwordWarning', b'86400'),
        (ldap.MOD_REPLACE, CONFIG_ATTR, b'off')])

    def fin():
        """Resets the defaults"""

        log.info('Reset the defaults')
        for key in attrs.keys():
            topology_st.standalone.modify_s(DN_CONFIG, [
                (ldap.MOD_REPLACE, key, ensure_bytes(attrs[key]))
            ])

    request.addfinalizer(fin)
    # A short sleep is required after modifying password policy or cn=config
    time.sleep(0.5)


@pytest.fixture
def add_user(topology_st, request):
    """Adds a user for binding"""

    user_data = {'objectClass': b'top person inetOrgPerson'.split(),
                 'uid': b'tuser',
                 'cn': b'test user',
                 'sn': b'user',
                 'userPassword': USER_PASSWD}

    log.info('Add the user')

    topology_st.standalone.add_s(Entry((USER_DN, user_data)))

    def fin():
        """Removes the user entry"""

        log.info('Remove the user entry')
        topology_st.standalone.delete_s(USER_DN)

    request.addfinalizer(fin)


@pytest.fixture
def local_policy(topology_st, add_user):
    """Sets fine grained policy for user entry"""

    log.info("Setting fine grained policy for user ({})".format(USER_DN))

    subprocess.call(['%s/ns-newpwpolicy.pl' % topology_st.standalone.get_sbin_dir(),
                     '-D', DN_DM,
                     '-w', PASSWORD, '-h', HOST_STANDALONE,
                     '-p', str(PORT_STANDALONE), '-U', USER_DN,
                     '-Z', SERVERID_STANDALONE])
    # A short sleep is required after modifying password policy
    time.sleep(0.5)


def get_password_warning(topology_st):
    """Gets the password expiry warning time for the user"""

    res_type = res_data = res_msgid = res_ctrls = None
    result_id = ''

    log.info('Bind with the user and request the password expiry warning time')

    result_id = topology_st.standalone.simple_bind(USER_DN, USER_PASSWD,
                                                   serverctrls=[PasswordPolicyControl()])
    res_type, res_data, res_msgid, res_ctrls = \
        topology_st.standalone.result3(result_id)
    # Return the control
    return res_ctrls


def set_conf_attr(topology_st, attr, val):
    """Sets the value of a given attribute under cn=config"""

    log.info("Setting {} to {}".format(attr, val))
    topology_st.standalone.modify_s(DN_CONFIG, [(ldap.MOD_REPLACE, attr, ensure_bytes(val))])
    # A short sleep is required after modifying cn=config
    time.sleep(0.5)


def get_conf_attr(topology_st, attr):
    """Gets the value of a given
    attribute under cn=config entry
    """

    entry = topology_st.standalone.getEntry(DN_CONFIG, ldap.SCOPE_BASE,
                                            '(objectClass=*)', [attr])
    val = entry.getValue(attr)
    # Return the value if no exeception is raised
    return val


@pytest.mark.parametrize("value", (' ', 'junk123', 'on', 'off'))
def test_different_values(topology_st, value):
    """Try to set passwordSendExpiringTime attribute
    to various values both valid and invalid

    :id: 3e6d79fb-b4c8-4860-897e-5b207815a75d
    :setup: Standalone instance
    :steps:
        1. Try to set passwordSendExpiringTime to 'on' and 'off'
           under cn=config entry
        2. Try to set passwordSendExpiringTime to ' ' and 'junk123'
           under cn=config entry
        3. Run the search command to check the
           value of passwordSendExpiringTime attribute
    :expectedresults:
        1. Valid values should be accepted and saved
        2. Should be rejected with an OPERATIONS_ERROR
        3. The attribute should be changed for valid values
           and unchanged for invalid
    """

    log.info('Get the default value')
    defval = get_conf_attr(topology_st, CONFIG_ATTR)

    if value not in ('on', 'off'):
        log.info('An invalid value is being tested')
        with pytest.raises(ldap.OPERATIONS_ERROR):
            set_conf_attr(topology_st, CONFIG_ATTR, value)

        log.info('Now check the value is unchanged')
        assert get_conf_attr(topology_st, CONFIG_ATTR) == defval

        log.info("Invalid value {} was rejected correctly".format(value))
    else:
        log.info('A valid value is being tested')
        set_conf_attr(topology_st, CONFIG_ATTR, value)

        log.info('Now check that the value has been changed')
        assert get_conf_attr(topology_st, CONFIG_ATTR) == value

        log.info("{} is now set to {}".format(CONFIG_ATTR, value))

        log.info('Set passwordSendExpiringTime back to the default value')
        set_conf_attr(topology_st, CONFIG_ATTR, defval)


@pytest.mark.parametrize("value", (' ', 'junk123', 'on', 'off'))
def test_different_values(topology_st, value):
    """Try to set passwordSendExpiringTime attribute
    to various values both valid and invalid

    :id: 3e6d79fb-b4c8-4860-897e-5b207815a75d
    :setup: Standalone instance
    :steps:
        1. Try to set passwordSendExpiringTime to 'on' and 'off'
           under cn=config entry
        2. Try to set passwordSendExpiringTime to ' ' and 'junk123'
           under cn=config entry
        3. Run the search command to check the
           value of passwordSendExpiringTime attribute
    :expectedresults:
        1. Valid values should be accepted and saved
        2. Should be rejected with an OPERATIONS_ERROR
        3. The attribute should be changed for valid values
           and unchanged for invalid
    """

    log.info('Get the default value')
    defval = get_conf_attr(topology_st, CONFIG_ATTR)

    if value not in ('on', 'off'):
        log.info('An invalid value is being tested')
        with pytest.raises(ldap.OPERATIONS_ERROR):
            set_conf_attr(topology_st, CONFIG_ATTR, value)

        log.info('Now check the value is unchanged')
        assert get_conf_attr(topology_st, CONFIG_ATTR) == defval

        log.info("Invalid value {} was rejected correctly".format(value))
    else:
        log.info('A valid value is being tested')
        set_conf_attr(topology_st, CONFIG_ATTR, value)

        log.info('Now check that the value has been changed')
        assert str(get_conf_attr(topology_st, CONFIG_ATTR), 'utf-8') == value

        log.info("{} is now set to {}".format(CONFIG_ATTR, value))

        log.info('Set passwordSendExpiringTime back to the default value')
        set_conf_attr(topology_st, CONFIG_ATTR, defval)


def test_expiry_time(topology_st, global_policy, add_user):
    """Test whether the password expiry warning
    time for a user is returned appropriately

    :id: 7adfd395-9b25-4cc0-9b71-14710dc1a28c
    :setup: Standalone instance, a user entry,
            Global password policy configured as below:
                passwordExp: on
                passwordMaxAge: 172800
                passwordWarning: 86400
                passwordSendExpiringTime: on
    :steps:
        1. Bind as the normal user
        2. Request password policy control for the user
        3. Bind as DM
    :expectedresults:
        1. Bind should be successful
        2. The password expiry warning time for the user should be returned
        3. Bind should be successful
    """

    res_ctrls = None

    log.info('Get the password expiry warning time')
    log.info("Binding with ({}) and requesting the password expiry warning time" \
             .format(USER_DN))
    res_ctrls = get_password_warning(topology_st)

    log.info('Check whether the time is returned')
    assert res_ctrls

    log.info("user's password will expire in {:d} seconds" \
             .format(res_ctrls[0].timeBeforeExpiration))

    log.info("Rebinding as DM")
    topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)


@pytest.mark.parametrize("attr,val", [(CONFIG_ATTR, 'off'),
                                      ('passwordWarning', '3600')])
def test_password_warning(topology_st, global_policy, add_user, attr, val):
    """Test password expiry warning time by setting passwordSendExpiringTime to off
    and setting passwordWarning to a short value

    :id: 39f54b3c-8c80-43ca-856a-174d81c56ce8
    :setup: Standalone instance, a test user,
            Global password policy configured as below:
                passwordExp: on
                passwordMaxAge: 172800
                passwordWarning: 86400
                passwordSendExpiringTime: on
    :steps:
        1. Set passwordSendExpiringTime attribute to off or
           to on and passwordWarning to a small value (3600)
        2. Bind as the normal user
        3. Request the password expiry warning time
        4. Bind as DM
    :expectedresults:
        1. passwordSendExpiringTime and passwordWarning are set successfully
        2. Bind should be successful
        3. Password expiry warning time should be returned for the small value
           and should not be returned when passwordSendExpiringTime is off
        4. Bind should be successful
    """

    log.info('Set configuration parameter')
    set_conf_attr(topology_st, attr, val)

    log.info("Binding with ({}) and requesting password expiry warning time" \
             .format(USER_DN))
    res_ctrls = get_password_warning(topology_st)

    log.info('Check the state of the control')
    if not res_ctrls:
        log.info("Password Expiry warning time is not returned as {} is set to {}" \
                 .format(attr, val))
    else:
        log.info("({}) password will expire in {:d} seconds" \
                 .format(USER_DN, res_ctrls[0].timeBeforeExpiration))

    log.info("Rebinding as DM")
    topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)


def test_with_different_password_states(topology_st, global_policy, add_user):
    """Test the control with different password states

    :id: d297fb1a-661f-4d52-bb43-2a2a340b8b0e
    :setup: Standalone instance, a user entry,
            Global password policy configured as below:
                passwordExp: on
                passwordMaxAge: 172800
                passwordWarning: 86400
                passwordSendExpiringTime: on
    :steps:
        1. Expire user's password by changing
           passwordExpirationTime timestamp
        2. Try to bind to the server with the user entry
        3. Revert back user's passwordExpirationTime
        4. Try to bind with the user entry and request
           the control
        5. Bind as DM
    :expectedresults:
        1. Operation should be successful
        2. Operation should fail because of Invalid Credentials
        3. passwordExpirationTime is successfully changed
        4. Bind should be successful and the password expiry
           warning time should be returned
        5. Bind should be successful
    """

    res_ctrls = None

    log.info("Expire user's password by changing" \
             "passwordExpirationTime timestamp")
    old_ts = topology_st.standalone.search_s(USER_DN, ldap.SCOPE_SUBTREE,
                                             '(objectClass=*)', ['passwordExpirationTime'])[0].getValue(
        'passwordExpirationTime')
    log.info("Old passwordExpirationTime: {}".format(old_ts))
    new_ts = (dt_parse(old_ts) - datetime.timedelta(31)).strftime('%Y%m%d%H%M%SZ')
    log.info("New passwordExpirationTime: {}".format(new_ts))
    topology_st.standalone.modify_s(USER_DN, [(ldap.MOD_REPLACE, 'passwordExpirationTime', ensure_bytes(new_ts))])

    log.info("Attempting to bind with user {} and retrive the password" \
             " expiry warning time".format(USER_DN))
    with pytest.raises(ldap.INVALID_CREDENTIALS) as ex:
        res_ctrls = get_password_warning(topology_st)

    log.info("Bind Failed, error: {}".format(str(ex)))

    log.info("Rebinding as DM")
    topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)

    log.info("Reverting back user's passwordExpirationTime")
    topology_st.standalone.modify_s(USER_DN, [(ldap.MOD_REPLACE, 'passwordExpirationTime', ensure_bytes(old_ts))])

    log.info("Rebinding with {} and retrieving the password" \
             " expiry warning time".format(USER_DN))
    res_ctrls = get_password_warning(topology_st)

    log.info('Check that the control is returned')
    assert res_ctrls

    log.info("user's password will expire in {:d} seconds" \
             .format(res_ctrls[0].timeBeforeExpiration))

    log.info("Rebinding as DM")
    topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)


def test_default_behavior(topology_st, global_policy_default, add_user):
    """Test the default behavior of password expiry warning time

    :id: c47fa824-ee08-4b78-885f-bca4c42bb655
    :setup: Standalone instance, a user entry,
            Global password policy configured as below:
                passwordExp: on
                passwordMaxAge: 8640000
                passwordWarning: 86400
                passwordSendExpiringTime: off
    :steps:
        1. Bind as the normal user
        2. Request the control for the user
        3. Bind as DM
    :expectedresults:
        1. Bind should be successful
        2. No control should be returned
        3. Bind should be successful
    """

    res_ctrls = None

    log.info("Binding with {} and requesting the password expiry warning time" \
             .format(USER_DN))
    res_ctrls = get_password_warning(topology_st)

    log.info('Check that no control is returned')
    assert not res_ctrls

    log.info("Rebinding as DM")
    topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)


def test_when_maxage_and_warning_are_the_same(topology_st, global_policy_default, add_user):
    """Test the warning expiry when passwordMaxAge and
    passwordWarning are set to the same value.

    :id: e57a1b1c-96fc-11e7-a91b-28d244694824
    :setup: Standalone instance, a user entry,
            Global password policy configured as below:
                passwordExp: on
                passwordMaxAge: 86400
                passwordWarning: 86400
                passwordSendExpiringTime: off
    :steps:
        1. Bind as the normal user
        2. Change user's password to reset its password expiration time
        3. Request the control for the user
        4. Bind as DM
    :expectedresults:
        1. Bind should be successful
        2. Password should be changed and password's expiration time reset
        3. Password expiry warning time should be returned by the
           server since passwordMaxAge and passwordWarning are set
           to the same value
        4. Bind should be successful
    """

    log.info('Set the new values')
    topology_st.standalone.config.set('passwordMaxAge', '86400')
    res_ctrls = None

    log.info("First change user's password to reset its password expiration time")
    topology_st.standalone.simple_bind_s(USER_DN, USER_PASSWD)

    topology_st.standalone.modify_s(USER_DN, [(ldap.MOD_REPLACE,
                                               'userPassword', ensure_bytes(USER_PASSWD))])
    log.info("Binding with {} and requesting the password expiry warning time" \
             .format(USER_DN))
    res_ctrls = get_password_warning(topology_st)

    log.info('Check that control is returned even'
             'if passwordSendExpiringTime is set to off')
    assert res_ctrls

    log.info("user's password will expire in {:d} seconds" \
             .format(res_ctrls[0].timeBeforeExpiration))

    log.info("Rebinding as DM")
    topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)


def test_with_local_policy(topology_st, global_policy, local_policy):
    """Test the attribute with fine grained policy set for the user

    :id: ab7d9f86-8cfe-48c3-8baa-739e599f006a
    :setup: Standalone instance, a user entry,
            Global password policy configured as below:
                passwordExp: on
                passwordMaxAge: 172800
                passwordWarning: 86400
                passwordSendExpiringTime: on
            Fine grained password policy for the user using ns-newpwpolicy.pl
    :steps:
        1. Bind as the normal user
        2. Request the control for the user
        3. Bind as DM
    :expectedresults:
        1. Bind should be successful
        2. Password expiry warning time should not be returned for the user
        3. Bind should be successful
    """

    res_ctrls = None

    log.info("Attempting to get password expiry warning time for" \
             " user {}".format(USER_DN))
    res_ctrls = get_password_warning(topology_st)

    log.info('Check that the control is not returned')
    assert not res_ctrls

    log.info("Password expiry warning time is not returned")

    log.info("Rebinding as DM")
    topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)


if __name__ == '__main__':
    # Run isolated
    # -s for DEBUG mode
    CURRENT_FILE = os.path.realpath(__file__)
    pytest.main("-s %s" % CURRENT_FILE)
