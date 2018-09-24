VERSION = `git rev-parse --short HEAD`
TO := _

ifdef BUILD_NUMBER
NUMBER = $(BUILD_NUMBER)
else
NUMBER = 1
endif

ifdef JOB_BASE_NAME
PROJECT_ENCODED_SLASH = $(subst %2F,$(TO),$(JOB_BASE_NAME))
PROJECT = $(subst /,$(TO),$(PROJECT_ENCODED_SLASH))
# Run on CI
COMPOSE = docker-compose -f docker-compose.yml -p aioevsourcing_$(PROJECT)_$(NUMBER)
else
# Run Locally
COMPOSE = docker-compose -p aioevsourcing
endif

DEVPI_USER ?= dailymotion
DEVPI_PASS ?= test1234
DEVPI_INDEX ?= https://pypi.stg.dm.gg/dailymotion/dm2
DEVPI_PKG_NAME ?= aioevsourcing

PUBLISH_CMD = ./run.sh publish
PUBLISH_CMD += $(DEVPI_INDEX)
PUBLISH_CMD += $(DEVPI_USER)
PUBLISH_CMD += $(DEVPI_PASS)
PUBLISH_CMD += $(DEVPI_PKG_NAME)

PUBLISH_CMD := "$(PUBLISH_CMD)"

EXISTS_CMD = ./run.sh exists
EXISTS_CMD += $(DEVPI_INDEX)
EXISTS_CMD += $(DEVPI_USER)
EXISTS_CMD += $(DEVPI_PASS)
EXISTS_CMD += $(DEVPI_PKG_NAME)
EXISTS_CMD += $(DEVPI_PKG_VERSION)

EXISTS_CMD := "$(EXISTS_CMD)"


.PHONY: format
format:
	$(COMPOSE) build format
	$(COMPOSE) run format

.PHONY: check-format
check-format:
	$(COMPOSE) build check-format
	$(COMPOSE) run check-format

.PHONY: style
style: check-format
	$(COMPOSE) build style
	$(COMPOSE) run style

.PHONY: complexity
complexity:
	$(COMPOSE) build complexity
	$(COMPOSE) run complexity

.PHONY: test-unit
test-unit:
	$(COMPOSE) build test-unit
	$(COMPOSE) run test-unit

.PHONY: test
test: test-unit
