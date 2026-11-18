import { useDialog } from "naive-ui";

// Only the first caller may act on an open confirmation.
export function useConfirm() {
  const dialog = useDialog();
  let pending = false;
  return (content: string): Promise<boolean> => {
    if (pending) return Promise.resolve(false);
    pending = true;
    return new Promise((resolve) => {
      const finish = (accepted: boolean) => { pending = false; resolve(accepted); };
      dialog.warning({
        title: "确认操作", content, positiveText: "确认", negativeText: "取消",
        onPositiveClick: () => finish(true),
        onNegativeClick: () => finish(false),
        onClose: () => finish(false),
        onMaskClick: () => finish(false),
        onEsc: () => finish(false),
      });
    });
  };
}
