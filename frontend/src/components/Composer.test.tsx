import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends typed text and keeps the interrupt control", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const onChange = vi.fn();
    render(
      <Composer
        lang="en"
        value="VPN-ERR-4012"
        interim=""
        placeholder="Describe the fault"
        sendLabel="Send"
        interruptLabel="Interrupt"
        micLabel="Mic"
        listening={false}
        sttReady={false}
        pending={false}
        onChange={onChange}
        onSend={onSend}
        onInterrupt={() => undefined}
        onMic={() => undefined}
      />,
    );
    expect(screen.getByTestId("mic-button")).toBeDisabled();
    await user.click(screen.getByTestId("send-button"));
    expect(onSend).toHaveBeenCalledOnce();
    expect(screen.getByTestId("interrupt-button")).toBeDisabled();
  });
});
