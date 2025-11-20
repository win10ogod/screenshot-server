"""测试 windows-capture API"""
import time

try:
    from windows_capture import WindowsCapture, Frame, InternalCaptureControl

    print("windows-capture imported successfully")

    # 测试 Frame 对象属性
    print("\nFrame class attributes:")
    print(dir(Frame))

    # 测试捕获
    frame_count = 0

    def on_frame(frame: Frame, control: InternalCaptureControl):
        global frame_count
        frame_count += 1

        print(f"\n=== Frame {frame_count} ===")
        print(f"Frame type: {type(frame)}")
        print(f"Frame dir: {dir(frame)}")

        # 测试各种可能的属性
        for attr in ['buffer', 'data', 'frame_buffer', 'width', 'height']:
            if hasattr(frame, attr):
                val = getattr(frame, attr)
                print(f"frame.{attr}: {type(val)} (len={len(val) if isinstance(val, (bytes, bytearray)) else 'N/A'})")

        # 停止测试
        if frame_count >= 3:
            control.stop()

    print("\nCreating WindowsCapture...")
    capture = WindowsCapture()

    # 使用装饰器注册回调（正确的 API 用法）
    @capture.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
        on_frame(frame, control)

    @capture.event
    def on_closed():
        print("\nCapture session closed")

    print("Starting capture (will capture 3 frames)...")
    capture.start()  # start() 不接受参数

    print(f"\nCaptured {frame_count} frames successfully")

except ImportError as e:
    print(f"Import error: {e}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
