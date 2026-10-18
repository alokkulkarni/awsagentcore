// Only the classes the page uses for an audio call. The SDK's own index is imported (its modules
// depend on each other in a set order); build_chime.sh stubs the messaging client, which needs Node.
export { ConsoleLogger, DefaultDeviceController, DefaultMeetingSession, LogLevel, MeetingSessionConfiguration }
  from 'amazon-chime-sdk-js';
