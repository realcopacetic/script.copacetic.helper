import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
DEBUG = xbmc.LOGDEBUG
DIALOG = xbmcgui.Dialog()

def log_and_execute(action):
    xbmc.log('{}: EXECUTE: {}'.format(ADDON_ID,action), DEBUG)
    xbmc.executebuiltin(action)

def dialog_yesno(**kwargs):
    heading = kwargs.get('heading', '')
    message = kwargs.get('message', '')
    yes_actions = kwargs.get('yes_actions', '').split('|')
    no_actions = kwargs.get('no_actions', '').split('|')

    if DIALOG.yesno(heading, message):
        for action in yes_actions:
            log_and_execute(action)
    else:
        for action in no_actions:
            log_and_execute(action)