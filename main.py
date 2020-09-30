""" Lisz main module implemented via the Kivy framework.

The node data implementations for this application is documented in the module :mod:`ae.lisz_app_data`.

  app version history:
    0.1     first version with icon images for Irmi, migrated from github/AndiEcker/maio (after the commit:
            https://github.com/AndiEcker/maio/commit/727ead037e865dd359e0dc4bbc2da84ae20c9e58).
    0.2     first beta implementation of font_size/_ink user preferences.
    0.3     added light theme and app state version and removed leftovers from trying to use kivy config/settings.
    0.4     added image and sound file loaders and finders, implemented ae.files with FilesRegister.
    0.5     added vibrate pattern support (play_vibrate()).
    0.6     second roll-out of a stable version for Irmi.
    0.7     added flow path quick jump dropdown, rearranged and enhanced the user preferences drop down menu,
            added border lines around item box-layout and buttons.
    0.8     increased item id editor height, removed border lines (ugly on some devices and wrong width after swap of
            screen orientation), prevent edit item box covered by mobile keyboard (setting Window.softinput_mode).
    0.9     select_button of node displaying select child relation and allow de-/sel of node children (all sel/un-sel).
    1.0     third roll-out of stable version for Irmi.
    1.1     node sub-item selection confirmation, enhance edit item box position (was still covered by kbd sometimes)
            and de-/select item performance.
    1.2     i18n of user message strings in python and kv code with f-string support.
    1.3     added kivy settings dialog and kbd_input_mode debug feature.
    1.4     backup and restore of list nodes and leaves to the documents/lisz folder and some popup/UI enhancements.
    1.5     added help system for flow and app state changes (fourth/fifth/sixth roll-out as version 1.5.4/6/8/11).
            added clipboard support (copy/paste single item or sub-lists-tree), enhanced import/export,
            consolidated ae_/_press names.

    TODO: peer-to-peer send of a node - from one to other Lisz app.
    TODO: add FileChooser for import/export providing all placeholders from ae.paths.
    TODO: backup of the config file (including all nodes) to the cloud (e.g. google drive).
    TODO: keyboard-drag-drop ctr+D
    TODO: auto-jump to destination(parent/sub) list in mouse-drag-drop
"""
from copy import deepcopy
from typing import Any, Dict, Iterator, List, Optional, Tuple

from kivy.animation import Animation
from kivy.app import App
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.input import MotionEvent
from kivy.properties import DictProperty, NumericProperty, ObjectProperty, BooleanProperty, StringProperty
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.dropdown import DropDown
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget

from ae.gui_app import id_of_flow, flow_action, flow_key
from ae.lisz_app_data import FLOW_PATH_ROOT_ID, FOCUS_FLOW_PREFIX, node_from_literal, LiszDataMixin, LiszItem, LiszNode
from ae.kivy_app import FlowDropDown, FlowToggler, LOVE_VIBRATE_PATTERN, FlowPopup, KivyMainApp, get_txt


__version__ = '1.5.11'


def selectable_and_total_sub_items(node: LiszNode, selected: int = 0, total: int = 0) -> Tuple[int, int]:
    """ determine the number of selectable and total leaf items in the passed node and their sub-nodes.

    :param node:            starting node.
    :param selected:        initial amount of selected items.
    :param total:           initial total amount of item leaves.
    :return:                tuple of selectable and total leaf items.
                            Dividing [0] by [1] results in a value between 0.0 and 1.0 reflecting the relation
                            between selected and unselected leaves.
    """
    for item in node:
        if 'node' in item:
            selected, total = selectable_and_total_sub_items(item['node'], selected, total)
        else:
            if item.get('sel'):
                selected += 1
            total += 1

    return selected, total


class DropPlaceholder(Widget):
    """ placeholder for to display screen box to drop a dragged item onto. """
    destination = StringProperty()


class ItemDeletionConfirmPopup(FlowPopup):
    """ confirm dialog for to delete an list leaf or node. """
    item_id = StringProperty()
    node_only = BooleanProperty()


class ItemSelConfirmPopup(FlowPopup):
    """ confirm dialog for to de-/select the sub-leaves of a list node. """
    item_id = StringProperty()
    set_sel_to = BooleanProperty()


class ListFiltButton(FlowToggler):
    """ widget for to toggle filter of selected/unselected list items. """
    name_part = StringProperty()


class NodeInfoOpenPopup(FlowDropDown):
    """ drop down for to show node info. """
    node_info = DictProperty()


class NodeItem(FocusBehavior, BoxLayout):
    """ widget to display data item in list. """
    item_data: LiszItem = ObjectProperty()          # DictProperty would create new instance of our node item dict
    item_idx = NumericProperty()

    def __init__(self, **kwargs):
        self.item_data = kwargs.pop('item_data', dict(id=''))
        self.item_idx = kwargs.pop('item_idx', -1)

        if 'node' in self.item_data:
            node = self.item_data['node']
            sel, tot = selectable_and_total_sub_items(node)
            sel_factor = sel / (tot or 1.0)
            self.item_data['sel'] = sel_factor
        else:
            sel_factor = 0.0
        self.sel_majority_size_hint_x = max(sel_factor, 1 - sel_factor)
        self.sel_minority_size_hint_x = min(sel_factor, 1 - sel_factor)

        kivy_app = App.get_running_app()    # FrameworkApp
        self.app_root = kivy_app.root       # main view
        self.main_app = kivy_app.main_app   # kivy/console app
        self.space = self.main_app.font_size / 6.0

        super().__init__(**kwargs)

        self.nic = kivy_app.root.ids.itemsContainer
        self.dragged_from_node = None
        self.dragging_to_parent_widget_instance = None
        self.dragging_to_parent_widget_idx = -1

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """ move gliding list item widget """
        if self.main_app.help_layout or not self.ids.dragHandle.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        touch.grab(self)
        touch.ud[self] = 'drag'
        self.dragged_from_node = self.main_app.current_node_items
        self.main_app.dragging_item_idx = self.item_idx
        assert self.item_idx == self.dragged_from_node.index(self.item_data), \
            f"{self.item_idx} != {self.dragged_from_node.index(self.item_data)} item-data={self.item_data}"
        self.parent.remove_widget(self)
        self.x = touch.pos[0] - self.ids.dragHandle.x - self.ids.dragHandle.width / 2
        self.y = Window.mouse_pos[1] - self.height / 2
        self.app_root.add_widget(self)

        return True

    def on_touch_move(self, touch: MotionEvent) -> bool:
        """ move gliding list item widget """
        if touch.grab_current is not self or touch.ud.get(self) != 'drag':
            return False

        self.pos = touch.pos[0] - self.ids.dragHandle.x - self.ids.dragHandle.width / 2, touch.pos[1] - self.height / 2

        ma = self.main_app
        svw = self.nic.parent
        if svw.collide_point(*svw.parent.to_local(*touch.pos)):
            placeholders = list(ma.placeholders_above.values()) + list(ma.placeholders_below.values())
            for child_idx, niw in enumerate(self.nic.children):
                ic_pos = self.nic.to_local(*svw.to_local(*touch.pos))
                if niw not in placeholders and niw.collide_point(*ic_pos) \
                        and ma.create_placeholder(child_idx, niw, ic_pos[1]):
                    self._restore_menu_bar()
                    return True

        mb = self.app_root.ids.menuBar
        bb = mb.ids.leaveItemButton     # .children[-3]
        if not bb.disabled and bb.collide_point(*mb.to_local(*touch.pos)):
            ma.cleanup_placeholder()
            if not self.dragging_to_parent_widget_instance:
                self.dragging_to_parent_widget_instance = bb
                self.dragging_to_parent_widget_idx = mb.children.index(bb)
                mb.remove_widget(bb)
                ph = Factory.DropPlaceholder(destination='leave', size_hint_x=None, size=(Window.width / 2, mb.height))
                mb.add_widget(ph, index=self.dragging_to_parent_widget_idx)
        elif touch.pos[1] < self.height:
            svw.scroll_y = min(max(0, svw.scroll_y - svw.convert_distance_to_scroll(0, self.height)[1]), 1)
        elif touch.pos[1] > svw.top - self.height:
            svw.scroll_y = min(max(0, svw.scroll_y + svw.convert_distance_to_scroll(0, self.height)[1]), 1)

        return True

    def on_touch_up(self, touch: MotionEvent) -> bool:
        """ drop / finish drag """
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        if touch.ud[self] != 'drag':
            return False

        ma = self.main_app

        dst_node_path = None
        child_id = ''
        moved = False
        if self.dragging_to_parent_widget_instance or ma.placeholders_above or ma.placeholders_below:
            src_node = self.dragged_from_node
            assert src_node.index(self.item_data) == self.item_idx
            dst_item_id = ''
            if self.dragging_to_parent_widget_instance:
                dst_node_path = ma.flow_path[:-1]
            elif ma.placeholders_above and ma.placeholders_below:   # drop into node
                item_idx = list(ma.placeholders_below.keys())[0]
                child_id = src_node[item_idx]['id']
                dst_node_path = ma.flow_path + [id_of_flow('enter', 'item', child_id), ]
            else:
                if ma.placeholders_above:
                    item_idx = list(ma.placeholders_above.keys())[0]
                else:
                    item_idx = list(ma.placeholders_below.keys())[0] + 1
                dst_item_id = src_node[item_idx]['id'] if item_idx < len(src_node) else ''
            moved = ma.move_item(src_node, self.item_data['id'], dropped_path=dst_node_path, dropped_id=dst_item_id)

        self._restore_menu_bar()
        self.app_root.remove_widget(self)
        ma.cleanup_placeholder()

        ma.dragging_item_idx = None
        self.dragged_from_node = None
        touch.ungrab(self)

        if moved:
            ma.play_sound('edited')
            ma.save_app_states()
            moved = not child_id and dst_node_path is not None
        # refresh and maybe set/change focus; on_flow_id() with 'focus' flow action does also a full refresh/redraw
        if moved:
            ma.refresh_all()
        else:
            flow_id = id_of_flow('focus', 'item', child_id or self.item_data['id'])
            if flow_id == ma.flow_id:
                # remove focus from focused item - allowing clipboard item copies of current node (not current item)
                ma.change_app_state('flow_id', id_of_flow('', ''))    # using instead change_flow() recovers last focus
            else:
                ma.change_flow(flow_id)

        return True

    def _restore_menu_bar(self):
        if self.dragging_to_parent_widget_instance:
            mb = self.app_root.ids.menuBar
            bb = self.dragging_to_parent_widget_instance
            ph = mb.children[self.dragging_to_parent_widget_idx]
            mb.remove_widget(ph)
            mb.add_widget(bb, index=self.dragging_to_parent_widget_idx)
            # not needed: self.dragging_to_parent_widget_idx = -1
            self.dragging_to_parent_widget_instance = None


class LiszApp(KivyMainApp, LiszDataMixin):
    """ app class """
    dragging_item_idx: Optional[int] = None                 #: index of dragged data if in drag mode else None
    items_container: Optional[Widget]                       #: list container widget shortcut
    menu_bar_ids: Any                                       #: menu bar ids shortcut (is actually a DictProperty)
    placeholders_above: Dict[int, Widget] = dict()          #: added placeholder above widgets (used for drag+drop)
    placeholders_below: Dict[int, Widget] = dict()          #: added placeholder below widgets (used for drag+drop)
    refreshing_widgets: bool = False                        #: True only in refresh call (performance opt)

    def create_item_widgets(self, item_idx: int, nid: LiszItem) -> List[Widget]:
        """ create widgets for to display one item, optionally with placeholder markers

        :param item_idx:    index of item_data within current list.
        :param nid:         list item data.
        :return:            list of created widgets: one NodeItem widget with item_data from nid and
                            optional placeholders above/below.
        """
        widgets = list()

        if item_idx in self.placeholders_above:
            widgets.append(self.placeholders_above[item_idx])

        niw = Factory.NodeItem(item_data=nid, item_idx=item_idx)
        widgets.append(niw)
        assert niw.item_data is nid
        assert niw.item_idx == item_idx

        if item_idx in self.placeholders_below:
            widgets.append(self.placeholders_below[item_idx])

        return widgets

    def create_placeholder(self, child_idx: int, niw: Widget, touch_y: float) -> bool:
        """ create placeholder data structures. """
        child_idx -= self.cleanup_placeholder(child_idx=child_idx)
        part = (touch_y - niw.y) / niw.height
        item_idx = niw.item_idx
        self.vpo(f"LiszApp.create placeholder {child_idx:2} {item_idx:2} {niw.item_data['id'][:9]:9}"
                 f" {niw.y:4.2f} {touch_y:4.2f} {part:4.2f}")
        if 'node' in niw.item_data and 0.123 < part < 0.9:
            self.placeholders_above[item_idx] = Factory.DropPlaceholder(destination='enter', height=niw.height / 2.7)
            self.placeholders_below[item_idx] = Factory.DropPlaceholder(destination='enter', height=niw.height / 2.7)
            self.play_vibrate((0.03, 0.12, 0.09, 0.12, 0.09, 0.12))
        elif -0.111 < part < 1.11:
            placeholders = self.placeholders_above if part >= 0.501 else self.placeholders_below
            placeholders[item_idx] = Factory.DropPlaceholder(destination='current', height=niw.height * 1.11)
            self.play_vibrate((0.03, 0.09, 0.09, 0.09))
        else:
            return False

        # add widgets without redrawing (self.on_flow_id())
        nic = self.items_container
        for phw in self.placeholders_below.values():
            nic.add_widget(phw, index=child_idx)
            nic.height += phw.height
            child_idx += 1
        for phw in self.placeholders_above.values():
            nic.add_widget(phw, index=child_idx + 1)
            nic.height += phw.height

        return True

    def cleanup_placeholder(self, child_idx: int = 0) -> int:
        """ cleanup placeholder data and widgets. """
        delta_idx = 0
        placeholders = list(self.placeholders_above.values()) + list(self.placeholders_below.values())
        for placeholder in placeholders:
            nic = placeholder.parent
            if nic:
                del_idx = nic.children.index(placeholder)
                if del_idx < child_idx:
                    delta_idx = 1
                nic.remove_widget(placeholder)
                nic.height -= placeholder.height

        self.placeholders_above.clear()
        self.placeholders_below.clear()

        return delta_idx

    def edit_item_finished(self, old_id: str, new_id: str, state: str):
        """ finished list add/edit callback from on_dismiss event of ItemEditor """
        self.vpo(f"LiszApp.edit_item_finished('{old_id}', '{new_id}', {state})")
        self.change_flow(id_of_flow('save', 'item', old_id), new_id=new_id, want_node=state == 'down')

    def export_node(self, flow_path: List[str], file_path: str = "", node: Optional[LiszNode] = None
                    ) -> Optional[Exception]:
        """ overwritten export node for overwrite file path default and for to log call and error.

        :param flow_path:   flow path of the node to export (def=OS documents folder / app name).
        :param file_path:   path to the folder wherein to store the node data (def=OS documents folder + app name).
        :param node:        explicit/filtered node items (if not passed then all items will be exported).
        :return:            `None` if node got exported without errors, else the raised exception.
        """
        if not file_path:
            file_path = self.documents_root_path
        self.vpo(f"LiszApp.export_node({flow_path}, {file_path})")

        exception = super().export_node(flow_path, file_path=file_path, node=node)
        if exception:
            self.po(f"LiszApp.export_node({flow_path}, {file_path}) exception: {exception}")
            self.show_message(str(exception), title=get_txt("export error"))

        return exception

    def on_clipboard_key_c(self, lit: str = ""):
        """ copy focused item or the currently displayed node items to the OS clipboard.

        :param lit:             string literal to copy (def=current_item_or_node_literal()).
        """
        if not lit:
            lit = self.current_item_or_node_literal()
        self.vpo(f"LiszApp.on_clipboard_key_c: copying {lit}")
        Clipboard.copy(lit)

    def on_clipboard_key_v(self):
        """ paste copied item or all items of the current node from the OS clipboard into the current node.
        """
        lit = Clipboard.paste()
        self.vpo(f"LiszApp.on_clipboard_key_v: pasting {lit}")
        items = node_from_literal(lit)
        err_msg = self.add_items(items)
        if err_msg:
            self.show_message(err_msg, title=get_txt("{count} error(s) in adding {len(items)} item(s)",
                                                     count=err_msg.count('\n') + 1))

        self.refresh_all()

    def on_clipboard_key_x(self):
        """ cut focused item or the currently displayed node items to the OS clipboard.
        """
        lit = self.current_item_or_node_literal()
        self.vpo(f"LiszApp.on_clipboard_key_x: cutting {lit}")
        Clipboard.copy(lit)
        if lit.startswith('['):
            for item in self.current_node_items:
                self.delete_item(item['id'])
        elif lit.startswith('{'):
            self.delete_item(flow_key(self.flow_id))
        else:
            self.delete_item(lit)
        self.refresh_all()

    def on_flow_id(self):
        """ refresh screen on update of flow id or path. """
        if flow_action(self.flow_id) in ('', 'focus'):
            self.refresh_all()

    def on_item_add(self, _item_id: str, _event_kwargs: Dict[str, Any]) -> bool:
        """ start/initiate the addition of a new list item """
        border = Popup.border.defaultvalue  # (bottom, right, top, left)
        height = self.font_size * 1.8 + border[0] + border[2]
        pwx, pwy = -border[3] / 2.1, Window.height - 2.1 * height
        self.prevent_keyboard_covering(pwy)
        pu = Factory.ItemEditor(title='',
                                pos_hint=dict(x=pwx / Window.width, y=pwy / Window.height),
                                size_hint=(0.99 + (border[1] + border[3]) / Window.width, height / Window.height),
                                background_color=(0.6, 0.9, 0.6, 0.6),
                                border=border,
                                separator_height=0,
                                title_size=0,
                                auto_width_minimum=Window.width,
                                auto_width_window_padding=0,
                                )
        # calc popup height: Popup widget in style.kv is adding dp(12) as padding and dp(16) to title font size
        # .. therefore remove title label widget from popup instance
        pu.children[0].remove_widget(pu.children[0].children[-1])

        pu.open()       # popup will call back self.edit_item_finished on dismiss/close

        return True

    def on_item_delete(self, item_id: str, event_kwargs: Dict[str, Any]) -> bool:
        """ delete item or node of this item """
        item_id = event_kwargs.get('item_id', item_id)
        assert item_id
        del_node = event_kwargs.get('del_node', False)
        self.delete_item(item_id, del_node)
        if not del_node:
            self.change_flow(id_of_flow('', ''))
        self.play_sound('deleted')
        self.refresh_all()
        return True

    def on_item_edit(self, _item_id: str, _event_kwargs: Dict[str, Any]) -> bool:
        """ edit list item """
        self.vpo(f"LiszApp.on_item_edit({_item_id} {_event_kwargs})")
        item_id = flow_key(self.flow_id)
        niw = self.widget_by_id(item_id)
        nic = self.items_container
        svw = nic.parent
        svw.scroll_to(niw, animate=False)

        border = Popup.border.defaultvalue   # (bottom, right, top, left)
        pos = niw.to_window(*niw.pos)
        pwx = max(-border[3] / 2.01, pos[0] - border[3])
        pwy = min(max(0, pos[1] - border[0]), svw.height - niw.height - border[0])
        self.prevent_keyboard_covering(pwy)
        height = niw.height * 1.8 / 1.5 + border[0] + border[2]
        pu = Factory.ItemEditor(title=niw.item_data['id'],
                                pos_hint=dict(x=pwx / Window.width, y=pwy / Window.height),
                                size_hint=(None, None), size=(svw.width + border[1] + border[3], height),
                                background_color=(0.9, 0.6, 0.6, 0.6),
                                border=border,
                                separator_height=0,
                                title_size=0,
                                auto_width_minimum=Window.width,
                                auto_width_window_padding=0,
                                )
        # calc popup height: Popup widget in style.kv is adding dp(12) as padding and dp(16) to title font size
        # .. therefore remove title label widget from popup instance (on some devices the height was too small)
        pu.children[0].remove_widget(pu.children[0].children[-1])

        pu.open()                                   # popup will call edit_item_finished() on dismiss/close

        return True

    def on_item_enter(self, item_id: str, event_kwargs: Dict[str, Any]) -> bool:
        """ animate entering node. """
        nic = self.items_container
        ani = Animation(x=Window.width, d=0.003) + Animation(x=nic.x, d=0.21, t='out_quint')
        ani.start(nic)
        return super().on_item_enter(item_id, event_kwargs)

    def on_item_leave(self, item_id: str, event_kwargs: Dict[str, Any]) -> bool:
        """ animate leaving of node. """
        nic = self.items_container
        ani = Animation(y=100, right=100, d=0.006) + Animation(y=nic.y, right=nic.right, d=0.21, t='out_quint')
        ani.start(nic)
        return super().on_item_leave(item_id, event_kwargs)

    def on_item_save(self, item_id: str, event_kwargs: Dict[str, Any]) -> bool:
        """ update item specified by flow key using the new values/changes given in event_kwargs. """
        self.vpo(f"LiszApp.on_item_save('{item_id}', {event_kwargs})")

        add_item = (item_id == '')
        item_idx = -1 if add_item else self.find_item_index(item_id)

        action_or_err = self.edit_validate(item_idx, **event_kwargs)

        if action_or_err:
            if action_or_err.startswith('request_delete_confirmation'):
                self.change_flow(id_of_flow('confirm', 'item_deletion', item_id),
                                 popup_kwargs=dict(node_only=action_or_err.endswith('_for_node')))
            else:
                self.show_message(action_or_err,
                                  title=get_txt("error on adding new item '{item_id}'" if add_item else
                                                "error on editing item '{item_id}'"))

            return False

        if add_item:  # new list item added (with non-empty new_id) at index 0 of the current node
            item_idx = 0

        self.play_vibrate(LOVE_VIBRATE_PATTERN)
        event_kwargs['flow_id'] = id_of_flow('focus', 'item', self.current_node_items[item_idx]['id'])

        self.save_app_states()
        return True

    def on_key_press(self, modifiers: str, key_code: str) -> bool:
        """ check key press event for to be handled and processed as command/action. """
        popups_open = list(self.popups_opened())
        if popups_open:
            if key_code in ('enter', 'escape'):
                popups_open[-1].dismiss()
                return True
            return False

        return super().on_key_press(modifiers, key_code)

    def on_kivy_app_start(self):
        """ callback after app init/build for to draw/refresh gui. """
        root_ids = self.framework_root.ids
        self.items_container = root_ids.itemsContainer
        self.menu_bar_ids = root_ids.menuBar.ids
        self.refresh_all()

    def on_node_import(self, _flow_key: str, event_kwargs: Dict[str, Any]) -> bool:
        """ import single node items to the node and index specified by event_kwargs[' flow key. """
        node = event_kwargs['node_to_import']
        add_node_id = event_kwargs.get('add_node_id', '')
        parent_node = event_kwargs.get('import_items_node', self.current_node_items)
        parent_index = event_kwargs.get('import_items_index', 0)
        self.vpo(f"LiszApp.on_import_node({node}, {add_node_id}, {parent_node}, {parent_index})")

        if add_node_id:
            err_msg = self.import_node(add_node_id, node, parent=parent_node, item_index=parent_index)
        else:
            err_msg = self.import_items(node, parent=parent_node, item_index=parent_index)
        if err_msg:
            self.po(f"LiszApp.on_import_node error: {err_msg}")
            self.show_message(err_msg, title=get_txt("import error(s)", count=err_msg.count("\n") + 1))

        self.save_app_states()
        self.refresh_all()
        return True

    def on_node_jump(self, item_id: str, event_kwargs: Dict[str, Any]) -> bool:
        """ overwrite to ensure close of drop down. """
        accepted = super().on_node_jump(item_id, event_kwargs)
        drop_downs = list(self.popups_opened(classes=(Factory.FlowPathJumperOpenPopup, )))
        if drop_downs:
            drop_downs[-1].dismiss()        # .close() node jumper dropdown
        return accepted

    def on_node_paste(self, _flow_key: str, _event_kwargs: Dict[str, Any]) -> bool:
        """ flow change event handler called from the alt_add popup menu. """
        self.on_clipboard_key_v()
        return True

    def popups_opened(self, classes: Tuple[Widget, ...] = (Popup, DropDown)) -> Iterator[Widget]:
        """ determine tuple of all opened PopUp instances. """
        # PopUps/DropDowns are attached in reverse order to root layout or to app Window
        for wid in reversed(self.framework_root.children):
            if isinstance(wid, classes):
                yield wid
        for wid in reversed(self.framework_win.children):
            if isinstance(wid, classes):
                yield wid

    def refresh_node_widgets(self):
        """ refresh displayed node item widgets and mark current list item of filtered current node data. """
        assert not self.refreshing_widgets
        self.refreshing_widgets = True
        try:
            flow_id = self.flow_id
            self.vpo(f"LiszApp.refresh_node_widgets: flow='{flow_id}' path={self.flow_path}")
            self.filtered_indexes = list()

            lf_ds = self.menu_bar_ids.listFilterSelected.state == 'normal'
            lf_ns = self.menu_bar_ids.listFilterUnselected.state == 'normal'
            nic = self.items_container
            nic.clear_widgets()
            h = 0
            for item_idx, nid in enumerate(self.current_node_items):
                if item_idx != self.dragging_item_idx:
                    widgets = self.create_item_widgets(item_idx, nid)   # has to be created for to re-calc sel for nodes
                    sel_state = nid.get('sel')
                    if lf_ds and sel_state or lf_ns and sel_state != 1.0:
                        for niw in widgets:
                            nic.add_widget(niw)
                            h += niw.height
                            self.filtered_indexes.append(item_idx)
            nic.height = h

            # ensure that current leaf/node is visible - if still exists in current list
            if flow_action(flow_id) == 'focus':
                niw = self.widget_by_id(flow_key(flow_id))
                if niw:
                    nic.parent.scroll_to(niw, animate=False)
        finally:
            assert self.refreshing_widgets
            self.refreshing_widgets = False

    def show_add_options(self, widget: Widget) -> bool:
        """ open context menu with all available actions for to add/import new node/item(s).

        :param widget:          FlowButton to open this context menu.
        :return:                True if any add options are available and got displayed else False.
        """
        def add_import_options(info_text: str):
            """ add menu options for the current node. """
            info = self.node_info(node, what=() if self.verbose else ('selected_leaf_count', 'unselected_leaf_count'))
            if len(node) == 1:
                info['content'] = node[0]['id']
            info_text = str(info['selected_leaf_count'] + info['unselected_leaf_count']) + " items from " + info_text
            if node_id:
                info['name'] = node_id
                info_text = get_txt("node '{node_id}' with ") + info_text
            info_text += " to"
            child_maps.append(dict(kwargs=dict(
                text=info_text, tap_flow_id=id_of_flow('open', 'node_info'),
                tap_kwargs=dict(popup_kwargs=dict(node_info=info)),
                image_size=image_size, circle_fill_color=self.flow_path_ink, circle_fill_size=image_size,
                square_fill_color=self.flow_id_ink[:3] + (0.39,))))

            args_tpl: Dict[str, Any] = dict(
                tap_flow_id=id_of_flow('import', 'node'),
                tap_kwargs=dict(node_to_import=node, popups_to_close=('replace_with_data_map_container',)),
                image_size=image_size)

            if self.flow_path:
                kwargs = deepcopy(args_tpl)
                kwargs['text'] = get_txt("current list begin")
                if node_id:
                    kwargs['tap_kwargs']['add_node_id'] = node_id
                child_maps.append(dict(kwargs=kwargs))

                item_index = len(self.current_node_items)
                if item_index:
                    kwargs = deepcopy(args_tpl)
                    kwargs['text'] = get_txt("current list end")
                    kwargs['tap_kwargs']['import_items_index'] = item_index
                    if node_id:
                        kwargs['tap_kwargs']['add_node_id'] = node_id
                    child_maps.append(dict(kwargs=kwargs))

            kwargs = deepcopy(args_tpl)
            kwargs['text'] = get_txt("{FLOW_PATH_ROOT_ID} list begin")
            kwargs['tap_kwargs']['import_items_node'] = self.root_node
            if node_id:
                kwargs['tap_kwargs']['add_node_id'] = node_id
            child_maps.append(dict(kwargs=kwargs))

            item_index = len(self.root_node)
            if item_index:
                kwargs = deepcopy(args_tpl)
                kwargs['text'] = get_txt("{FLOW_PATH_ROOT_ID} list end")
                kwargs['tap_kwargs']['import_items_node'] = self.root_node
                kwargs['tap_kwargs']['import_items_index'] = item_index
                if node_id:
                    kwargs['tap_kwargs']['add_node_id'] = node_id
                child_maps.append(dict(kwargs=kwargs))

            if focused_id:
                item_index = self.find_item_index(focused_id)

                kwargs = deepcopy(args_tpl)
                kwargs['text'] = get_txt("before focused item '{focused_id}'")
                kwargs['tap_kwargs']['import_items_index'] = item_index
                if node_id:
                    kwargs['tap_kwargs']['add_node_id'] = node_id
                child_maps.append(dict(kwargs=kwargs))

                focused_item = self.item_by_id(focused_id)
                if 'node' in focused_item:
                    kwargs = deepcopy(args_tpl)
                    kwargs['text'] = get_txt("into focused sub-list '{focused_id}'")
                    kwargs['tap_kwargs']['import_items_node'] = focused_item['node']
                    if node_id:
                        kwargs['tap_kwargs']['add_node_id'] = node_id
                    child_maps.append(dict(kwargs=kwargs))

                kwargs = deepcopy(args_tpl)
                kwargs['text'] = get_txt("after focused '{focused_id}'")
                kwargs['tap_kwargs']['import_items_index'] = item_index + 1
                if node_id:
                    kwargs['tap_kwargs']['add_node_id'] = node_id
                child_maps.append(dict(kwargs=kwargs))

        self.vpo(f"LiszApp.show_add_options({widget})")
        image_size = (self.font_size * 1.35, self.font_size * 1.35)
        focused_id = flow_key(self.flow_id) if flow_action(self.flow_id) == 'focus' else ''
        child_maps = list()

        node = node_from_literal(Clipboard.paste())
        if node:
            node_id = ''
            add_import_options(get_txt("clipboard"))

        node_files = self.importable_node_files(folder_path=self.documents_root_path)
        for node_file_info in node_files:
            if child_maps:                      # add separator widget
                child_maps.append(dict(cls='Widget', kwargs=dict(size_hint_y=None, height=self.font_size / 3)))

            node_id, node, file_path, err_msg = node_file_info
            if not err_msg:
                add_import_options(get_txt("export file"))

                child_maps.append(dict(cls='Widget', kwargs=dict(size_hint_y=None, height=self.font_size / 3)))
                node_id = ''
                add_import_options(get_txt("export file"))

            elif self.verbose:
                child_maps.append(dict(kwargs=dict(
                    cls='ImageLabel',
                    text=node_id + " error: " + err_msg,
                    square_fill_color=(1, 0, 0, 0.39,))))

        if not child_maps:
            self.show_message(get_txt("neither clipboard nor '{self.documents_root_path}' contains items to import"),
                              title=get_txt("import error(s)", count=1))
            return False

        popup_kwargs = dict(parent=widget, child_data_maps=child_maps, auto_width_child_padding=self.font_size * 3)
        return self.change_flow(id_of_flow('open', 'alt_add'), popup_kwargs=popup_kwargs)

    def show_extract_options(self, widget: Widget, flow_path_text: str = '',
                             item: Optional[LiszItem] = None, sel_status: Optional[bool] = None) -> bool:
        """ open context menu with the available extract actions of the current context/flow/app-status (focus, debug).

        :param widget:          widget to show extract options for.
        :param flow_path_text:  flow path text for to identify the node to extract (def=self.flow_path).
        :param item:            data dict of the item represented by :paramref:`~show_extract_options.widget`.
        :param sel_status:      pass True / False to add option for to export selected / unselected items.
        :return:                True if extract options are available and got displayed else False.
        """
        def add_extract_options(node_flow_path: List[str], pre: str = ""):
            """ add extract options for the node specified by node_flow_path.

            :param node_flow_path:  flow path of node for to add extract options to the child_maps list.
            :param pre:             info button text prefix (for to mark the focused item).
            """
            node = self.flow_path_node(node_flow_path, strict=True)
            if not node or node_flow_path in added_nodes:
                return      # skip empty and already added nodes
            added_nodes.append(node_flow_path)
            parent_node_id = flow_key(self.flow_path[-1]) if self.flow_path else FLOW_PATH_ROOT_ID

            if child_maps:
                child_maps.append(dict(              # add separator widget
                    cls='Widget',
                    kwargs=dict(size_hint_y=None, height=self.font_size / 3)))

            copy_icon = id_of_flow('copy', 'node')
            image_size = (self.font_size * 1.29, self.font_size * 1.29)
            node_info = self.node_info(node,
                                       what=() if self.verbose else ('selected_leaf_count', 'unselected_leaf_count'))
            if parent_node_id:
                node_info['name'] = parent_node_id

            info_text = (f"{self.flow_path_text(node_flow_path, display_root=True)}"
                         f"   {node_info[('un' if sel_status is False else '') + 'selected_leaf_count']}"
                         f"/{node_info['selected_leaf_count'] + node_info['unselected_leaf_count']}")
            child_maps.append(dict(
                kwargs=dict(
                    text=pre + info_text,
                    tap_flow_id=id_of_flow('open', 'node_info', repr(node_flow_path)),
                    tap_kwargs=dict(popup_kwargs=dict(node_info=node_info)),
                    image_size=image_size,
                    circle_fill_color=self.flow_path_ink, circle_fill_size=image_size,
                    square_fill_color=self.flow_id_ink[:3] + (0.39, ))))

            attr_tpl = dict(tap_flow_id=id_of_flow('extract', 'node', repr(node_flow_path)),
                            tap_kwargs=dict(popups_to_close=('replace_with_data_map_container', ), extract_type=''),
                            icon_name=id_of_flow('export', 'node'), image_size=image_size)

            attrs = deepcopy(attr_tpl)
            attrs.update(text=get_txt("copy all node items"), icon_name=copy_icon)
            attrs['tap_kwargs']['extract_type'] = 'copy'
            child_maps.append(dict(kwargs=attrs))

            attrs = deepcopy(attr_tpl)
            attrs.update(text=get_txt("export all node items"))
            attrs['tap_kwargs']['extract_type'] = 'export'
            child_maps.append(dict(kwargs=attrs))

            if self.debug:
                attrs = deepcopy(attr_tpl)
                attrs.update(text=get_txt("cut all node items"), icon_name=id_of_flow('cut', 'node'))
                attrs['tap_kwargs']['extract_type'] = 'cut'
                child_maps.append(dict(kwargs=attrs))

                attrs = deepcopy(attr_tpl)
                attrs.update(text=get_txt("delete all node items"), icon_name=id_of_flow('delete', 'item'))
                attrs['tap_kwargs']['extract_type'] = 'delete'
                child_maps.append(dict(kwargs=attrs))

            if sel_status is not None:
                extract_filter = 'sel' if sel_status else 'unsel'
                ink = self.selected_item_ink if sel_status else self.unselected_item_ink

                attrs = deepcopy(attr_tpl)
                attrs.update(text=get_txt("copy {'' if sel_status else 'un'}selected node items"), icon_name=copy_icon,
                             circle_fill_color=ink, circle_fill_size=image_size)
                attrs['tap_kwargs']['extract_type'] = 'copy_' + extract_filter
                child_maps.append(dict(kwargs=attrs))

                attrs = deepcopy(attr_tpl)
                attrs.update(text=get_txt("export {'' if sel_status else 'un'}selected node items"),
                             circle_fill_color=ink, circle_fill_size=image_size)
                attrs['tap_kwargs']['extract_type'] = 'export_' + extract_filter
                child_maps.append(dict(kwargs=attrs))

        self.vpo(f"LiszApp.show_extract_options({widget}, {flow_path_text}, {item}, {sel_status})")
        flow_path = self.flow_path_from_text(flow_path_text) if flow_path_text else self.flow_path
        has_focus = flow_action(self.flow_id) == 'focus'
        flo_key = flow_key(self.flow_id)
        child_maps = list()
        added_nodes = list()

        node_id = item['id'] if item else ''
        if node_id and 'node' in item:
            add_extract_options(flow_path + [id_of_flow('enter', 'item', node_id)],
                                pre=FOCUS_FLOW_PREFIX if has_focus and node_id == flo_key else "")

        add_extract_options(flow_path)

        if has_focus and flo_key != node_id:
            item = self.item_by_id(flo_key)
            if 'node' in item:
                add_extract_options(flow_path + [id_of_flow('enter', 'item', flo_key)], pre=FOCUS_FLOW_PREFIX)

        if not child_maps:
            self.show_message(get_txt("no extract options available for this item/node"))
            return False

        popup_kwargs = dict(parent=widget, child_data_maps=child_maps, auto_width_child_padding=self.font_size * 3)
        return self.change_flow(id_of_flow('open', 'extract'), popup_kwargs=popup_kwargs)

    def widget_by_flow_id(self, flow_id: str) -> Optional[Any]:
        """ determine the widget referenced by the passed flow_id.

        :param flow_id:         flow id referencing the focused widget.
        :return:                widget that has the focus when the passed flow id is set.
        """
        return self.widget_by_id(flow_key(flow_id)) or super().widget_by_flow_id(flow_id)

    def widget_by_id(self, item_id: str) -> Optional[Widget]:
        """ search list item widget """
        nic = self.items_container
        for niw in nic.children:
            item_data = getattr(niw, 'item_data', None)
            if item_data and item_data['id'] == item_id:
                return niw


# app start
if __name__ in ('__android__', '__main__'):
    LiszApp(app_name='lisz', app_title="Irmi's Shopping Lisz").run_app()
