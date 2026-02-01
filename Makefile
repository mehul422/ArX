OPENROCKET_JAR ?= /Users/mehulverma422/Desktop/ArX/arx-os/backend/resources/jars/OpenRocket-23.09.jar
ORK_PATH ?= /Users/mehulverma422/Desktop/ArX/arx-os/backend/tests/testforai/rocket.ork
ENG_PATH ?= /Users/mehulverma422/Desktop/ArX/arx-os/backend/tests/power1us.eng
OPENROCKET_LOGBACK_CONFIG ?= /Users/mehulverma422/Desktop/ArX/arx-os/backend/tests/logback-test.xml

.PHONY: test

test:
	cd backend && OPENROCKET_JAR="$(OPENROCKET_JAR)" \
		ORK_PATH="$(ORK_PATH)" \
		ENG_PATH="$(ENG_PATH)" \
		OPENROCKET_LOGBACK_CONFIG="$(OPENROCKET_LOGBACK_CONFIG)" \
		python -m unittest discover -s tests
