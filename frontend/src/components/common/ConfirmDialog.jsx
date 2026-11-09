import Modal from './Modal.jsx'

export default function ConfirmDialog({ open, title = 'Are you sure?', message, confirmLabel = 'Confirm', onConfirm, onClose, danger = false }) {
  return <Modal open={open} title={title} onClose={onClose}><p>{message}</p><div className="modal-actions"><button className="button button-secondary" type="button" onClick={onClose}>Cancel</button><button className={`button${danger ? ' button-danger' : ' button-primary'}`} type="button" onClick={onConfirm}>{confirmLabel}</button></div></Modal>
}
