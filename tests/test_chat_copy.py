from PyQt6.QtWidgets import QApplication, QLabel

from ui import ChatWidget


def test_chat_message_can_be_copied_to_clipboard():
    app = QApplication.instance() or QApplication([])
    chat = ChatWidget()
    chat._add_bubble("Here is the complete message.", "ai")
    label = chat._box_lay.itemAt(0).widget().findChild(QLabel)

    flags = label.textInteractionFlags()
    assert flags & label.textInteractionFlags().TextSelectableByMouse
    assert flags & label.textInteractionFlags().TextSelectableByKeyboard

    chat._copy_message(label)
    assert app.clipboard().text() == "Here is the complete message."