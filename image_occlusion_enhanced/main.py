# -*- coding: utf-8 -*-
####################################################
##                                                ##
##           Image Occlusion Enhanced             ##
##                                                ##
##        Copyright (c) Glutanimate 2016          ##
##       (https://github.com/Glutanimate)         ##
##                                                ##
##     Original Image Occlusion 2.0 add-on is     ##
##         Copyright (c) 2012-2015 tmbb           ##
##           (https://github.com/tmbb)            ##
##                                                ##
####################################################

import os

from PyQt4.QtGui import QFileDialog, QAction, QKeySequence
from PyQt4.QtCore import QUrl
from aqt.qt import *

from aqt import mw, webview, deckchooser, tagedit
from aqt.editcurrent import EditCurrent
from aqt.editor import Editor
from aqt.addcards import AddCards
from aqt.utils import tooltip, showWarning, saveGeom, restoreGeom
from anki.hooks import wrap, addHook

import re
import tempfile
import urlparse, urllib

from config import *
from ngen import *
from dialogs import ImgOccEdit, ImgOccOpts, ioHelp
from resources import *

# SVG-Edit configuration
svg_edit_dir = os.path.join(os.path.dirname(__file__),
                            'svg-edit',
                            'svg-edit-2.6')
svg_edit_path = os.path.join(svg_edit_dir,
                            'svg-editor.html')
svg_edit_ext = "ext-image-occlusion.js,ext-arrows.js,\
ext-markers.js,ext-shapes.js,ext-eyedropper.js"
svg_edit_fonts = "'Helvetica LT Std', Arial, sans-serif"
svg_edit_queryitems = [('initStroke[opacity]', '1'),
                       ('initStroke[color]', '2D2D2D'),
                       ('initStroke[width]', '1'),
                       ('initTool', 'rect'),
                       ('text[font_family]', svg_edit_fonts),
                       ('extensions', svg_edit_ext)]

def path2url(path):
    return urlparse.urljoin(
      'file:', urllib.pathname2url(path.encode('utf-8')))

def img2path(img):
    imgpatt = r"""<img.*?src=(["'])(.*?)\1"""
    imgregex = re.compile(imgpatt, flags=re.I|re.M|re.S)  
    fname = imgregex.search(img)
    if not fname:
        return None
    fpath = os.path.join(mw.col.media.dir(),fname.group(2))
    if not os.path.isfile(fpath):
        return None
    else:
        return fpath

class ImgOccAdd(object):
    def __init__(self, ed, mode):
        self.ed = ed
        self.mode = mode
        self.opref = {} # original io session preference

        # load preferences
        loadPrefs(self)

    def selImage(self):
        note = self.ed.note
        opref = self.opref

        opref["tags"] = self.ed.tags.text()
        
        if self.mode != "add":
            # can only get the deck of the current note/card via a db call:
            opref["did"] = mw.col.db.scalar(
                    "select did from cards where id = ?", note.cards()[0].id)
            note_id = note[IO_FLDS['id']]
            opref["note_id"] = note_id
            opref["uniq_id"] = note_id.split('-')[0]
            opref["occl_tp"] = note_id.split('-')[1]
            opref["image"] = img2path(note[IO_FLDS['im']])
            opref["omask"] = img2path(note[IO_FLDS['om']])
            if None in opref:
                showWarning("IO card not configured properly for editing")
                return
            image_path = opref["image"] 
        else:
            opref["did"] = self.ed.parentWindow.deckChooser.selectedId()
            image_path = self.getImage(self.ed.parentWindow)
            if not image_path:
                return

        self.image_path = image_path
        self.callImgOccEdit()

    def getImage(self, parent=None):
        clip = QApplication.clipboard()
        if clip.mimeData().imageData():
            handle, image_path = tempfile.mkstemp(suffix='.png')
            clip.image().save(image_path)
            clip.clear()
        else:
            # retrieve last used image directory
            prev_image_dir = self.prefs["prev_image_dir"]
            if not os.path.isdir(prev_image_dir):
                prev_image_dir = IO_HOME
            image_path = QFileDialog.getOpenFileName(parent,
                         "Choose Image", prev_image_dir, 
                         "Image Files (*.png *jpg *.jpeg *.gif)")
        if not image_path:
            return None
        elif not os.path.isfile(image_path):
            tooltip("Not a valid image file.")
            return None
        else:
            self.prefs["prev_image_dir"] = os.path.dirname( image_path )
            savePrefs(self)
            return image_path

    def callImgOccEdit(self):
        width, height = imageProp(self.image_path)
        ofill = mw.col.conf['imgocc']['ofill']
        bkgd_url = path2url(self.image_path)
        opref = self.opref
        onote = self.ed.note
        mode = self.mode
        model = mw.col.models.byName(IO_MODEL_NAME)
        flds = model['flds']

        deck = mw.col.decks.nameOrNone(opref["did"])
        # use existing IO instance when available:
        try:
            mw.ImgOccEdit is not None
            mw.ImgOccEdit.resetWindow()
        except:
            mw.ImgOccEdit = ImgOccEdit(mw)
        dialog = mw.ImgOccEdit
        dialog.switchToMode(self.mode)
        dialog.setupFields(flds)

        url = QUrl.fromLocalFile(svg_edit_path)
        url.setQueryItems(svg_edit_queryitems)
        url.addQueryItem('initFill[color]', ofill)
        url.addQueryItem('dimensions', '{0},{1}'.format(width, height))
        url.addQueryItem('bkgd_url', bkgd_url)

        if mode != "add":
            for i in self.mflds:
                fn = i["name"]
                if fn in IO_FLDS_PRIV:
                    continue
                dialog.tedit[fn].setPlainText(onote[fn].replace('<br />', '\n'))
            svg_b64 = svgToBase64(opref["omask"])
            url.addQueryItem('source', svg_b64)

        dialog.svg_edit.setUrl(url)
        dialog.deckChooser.deck.setText(deck)
        dialog.tags_edit.setCol(mw.col)
        dialog.tags_edit.setText(opref["tags"])
        dialog.tedit[IO_FLDS['sc']].setPlainText(onote[IO_FLDS['sc']])

        if mode == "add":
            dialog.show()
        else:
            # modal dialog when editing
            dialog.exec_() 
      
    def onChangeImage(self):
        image_path = self.getImage()
        if not image_path:
            return
        width, height = imageProp(image_path)
        bkgd_url = path2url(image_path)
        mw.ImgOccEdit.svg_edit.eval("""
                        svgCanvas.setBackground('#FFF', '%s');
                        svgCanvas.setResolution(%s, %s);
                        //svgCanvas.zoomChanged('', 'canvas');
                    """ %(bkgd_url, width, height))
        self.image_path = image_path

    def onAddNotesButton(self, choice, edit=False):
        dialog = mw.ImgOccEdit
        svg_edit = dialog.svg_edit
        svg = svg_edit.page().mainFrame().evaluateJavaScript(
            "svgCanvas.svgCanvasToString();")
        
        (fields, tags) = self.getUserInputs(dialog)

        if edit:
            did = self.opref["did"]
            old_occl_tp = self.opref["occl_tp"]
        else:
            did = dialog.deckChooser.selectedId()
            old_occl_tp = None

        noteGenerator = genByKey(choice, old_occl_tp)
        gen = noteGenerator(self.ed, svg, self.image_path, 
                                    self.opref, tags, fields, did)        
        if edit:
            ret = gen.updateNotes()
        else:
            ret = gen.generateNotes()
        
        if ret == False:
            # user dismissed confirmation dialog
            return False

        if self.ed.note and self.ed.addMode:
            # Update Editor with modified tags and sources field
            self.ed.tags.setText(" ".join(tags))
            self.ed.saveTags()
            srcfld = IO_FLDS['sc']
            if srcfld in self.ed.note:
                self.ed.note[srcfld] = fields[srcfld]
            self.ed.loadNote()
            deck = mw.col.decks.nameOrNone(did)
            self.ed.parentWindow.deckChooser.deck.setText(deck)
        elif edit:
            QWebSettings.clearMemoryCaches() # refresh webview image cache

        mw.reset() # FIXME: causes glitches in editcurrent mode

    def getUserInputs(self, dialog):
        fields = {}
        for i in self.mflds:
            fn = i['name']
            if fn in IO_FLDS_PRIV:
                continue
            text = dialog.tedit[fn].toPlainText().replace('\n', '<br />')
            fields[fn] = text
        tags = dialog.tags_edit.text().split()
        return (fields, tags)


def onIoSettings(mw):
    dialog = ImgOccOpts(mw)
    dialog.exec_()

def onIoHelp():
    ioHelp("main")

def onImgOccButton(ed, mode):
    ioModel = mw.col.models.byName(IO_MODEL_NAME)
    if ioModel:
        ioFields = mw.col.models.fieldNames(ioModel)
        # note type integrity check
        if not all(x in ioFields for x in IO_FLDS.values()):
            showWarning('<b>Error:</b><br><br>Image Occlusion note type \
                not configured properly.Please make sure you did not \
                manually delete or rename any of the default fields.')
            return
    if mode != "add" and ed.note.model() != ioModel:
        tooltip("Can only edit notes with the %s note type" % IO_MODEL_NAME)
        return
    mw.ImgOccAdd = ImgOccAdd(ed, mode)
    mw.ImgOccAdd.selImage()

def onSetupEditorButtons(self):
    # Add IO button to Editor  
    if isinstance(self.parentWindow, AddCards):
        btn = self._addButton("new_occlusion", 
                lambda o=self: onImgOccButton(self, "add"),
                _("Alt+a"), _("Add Image Occlusion (Alt+A/Alt+O)"), 
                canDisable=False)
    elif isinstance(self.parentWindow, EditCurrent):
        btn = self._addButton("edit_occlusion",
                lambda o=self: onImgOccButton(self, "editcurrent"),
                _("Alt+a"), _("Edit Image Occlusion (Alt+A/Alt+O)"), 
                canDisable=False)
    else:
        btn = self._addButton("edit_occlusion",
                lambda o=self: onImgOccButton(self, "browser"),
                _("Alt+a"), _("Edit Image Occlusion (Alt+A/Alt+O)"), 
                canDisable=False)

    press_action = QAction(self.parentWindow, triggered=btn.animateClick)
    press_action.setShortcut(QKeySequence(_("Alt+o")))
    btn.addAction(press_action)


def onSetNote(self, node, hide=True, focus=False):
    """simple hack that hides the ID field on IO notes"""
    if (self.note and self.note.model()["name"] == IO_MODEL_NAME and
            self.note.model()['flds'][0]['name'] == IO_FLDS['id']):
        self.web.eval("""
            // hide first fname, field, and snowflake (FrozenFields add-on)
                document.styleSheets[0].addRule(
                    'tr:first-child .fname, #f0, #i0', 'display: none;');
            """)

# Set up menus
options_action = QAction("Image &Occlusion Enhanced Options...", mw)
help_action = QAction("Image &Occlusion Enhanced...", mw)
mw.connect(options_action, SIGNAL("triggered()"), 
            lambda o=mw: onIoSettings(o))
mw.connect(help_action, SIGNAL("triggered()"),
            onIoHelp)
mw.form.menuTools.addAction(options_action)
mw.form.menuHelp.addAction(help_action)


# Set up hooks
addHook('setupEditorButtons', onSetupEditorButtons)
Editor.setNote = wrap(Editor.setNote, onSetNote, "after")
