"use strict";
var ACDL = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __require = /* @__PURE__ */ ((x) => typeof require !== "undefined" ? require : typeof Proxy !== "undefined" ? new Proxy(x, {
    get: (a, b) => (typeof require !== "undefined" ? require : a)[b]
  }) : x)(function(x) {
    if (typeof require !== "undefined") return require.apply(this, arguments);
    throw Error('Dynamic require of "' + x + '" is not supported');
  });
  var __commonJS = (cb, mod) => function __require2() {
    return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
  };
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);
  var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);

  // (disabled):fs
  var require_fs = __commonJS({
    "(disabled):fs"() {
    }
  });

  // src/_standalone_entry.ts
  var standalone_entry_exports = {};
  __export(standalone_entry_exports, {
    Parser: () => Parser,
    Scanner: () => Scanner,
    renderPrompt: () => renderPrompt,
    renderPrompts: () => renderPrompts,
    renderPromptsSvg: () => renderPromptsSvg
  });

  // src/scanner.ts
  var NAMESPACE_KEYWORDS = /* @__PURE__ */ new Set([
    "env",
    "sys",
    "resp"
  ]);
  var CONTROL_KEYWORDS = /* @__PURE__ */ new Set([
    "If",
    "ElseIf",
    "Else",
    "ForEach",
    "Switch",
    "Case",
    "Default",
    "break",
    "continue",
    "Name",
    "for",
    "in",
    "Mark",
    "when",
    "not",
    "and",
    "or",
    "StrFrag",
    "RoleFrag",
    "Frag"
  ]);
  var LOGIC_OP = /* @__PURE__ */ new Set([
    "=",
    "!",
    "<",
    ">",
    "&",
    "|",
    "^"
  ]);
  var ARITH_OP = /* @__PURE__ */ new Set([
    "-",
    "+",
    "%",
    "*",
    "/"
  ]);
  var SYMBOLS = /* @__PURE__ */ new Set([
    ":",
    ";",
    ".",
    ",",
    "(",
    ")",
    "{",
    "}",
    "[",
    "]",
    "@",
    "#",
    "$",
    "?",
    "!",
    "_"
  ]);
  var Scanner = class {
    constructor(input) {
      __publicField(this, "pos", 0);
      __publicField(this, "line", 1);
      __publicField(this, "col", 1);
      __publicField(this, "input");
      this.input = input;
    }
    nextToken() {
      this.skipWhitespace();
      if (this.isEOF()) {
        return { type: "EOF", value: null, line: this.line, col: this.col };
      }
      const ch = this.peek();
      if (ch === "/" && this.peekNext() === "/") {
        return this.readComment();
      }
      if (ch === "\u2026") {
        const col = this.col;
        this.advance();
        return { type: "RANGE", value: "\u2026", line: this.line, col };
      }
      if (ch === ".") {
        if (this.peekNext() === "." && this.input[this.pos + 2] === ".") {
          const col = this.col;
          this.advance();
          this.advance();
          this.advance();
          return { type: "RANGE", value: "...", line: this.line, col };
        }
      }
      if (LOGIC_OP.has(ch)) {
        const col = this.col;
        const value = this.advance();
        return {
          type: "LOGIC_OP",
          value,
          line: this.line,
          col
        };
      }
      if (ARITH_OP.has(ch)) {
        const col = this.col;
        const value = this.advance();
        return {
          type: "ARITH_OP",
          value,
          line: this.line,
          col
        };
      }
      if (ch === '"') {
        return this.readString();
      }
      if (SYMBOLS.has(ch)) {
        return this.readSymbol();
      }
      if (this.isDigit(ch)) {
        return this.readNumber();
      }
      if (this.isIdentStart(ch)) {
        return this.readIdentifier();
      }
      throw this.error(`Unexpected character '${ch}'`);
    }
    /* ───────────── token readers ───────────── */
    readComment() {
      const startCol = this.col;
      this.advance();
      this.advance();
      let value = "";
      while (!this.isEOF() && this.peek() !== "\n" && this.peek() !== "}") {
        value += this.advance();
      }
      return {
        type: "COMMENT",
        value: value.trim(),
        line: this.line,
        col: startCol
      };
    }
    readString() {
      const startCol = this.col;
      this.advance();
      let value = "";
      while (!this.isEOF()) {
        const ch = this.peek();
        if (ch === '"') {
          this.advance();
          return {
            type: "STRING",
            value,
            line: this.line,
            col: startCol
          };
        }
        if (ch === "\\") {
          this.advance();
          if (this.isEOF()) {
            throw this.error("Unterminated string literal");
          }
          const esc = this.advance();
          switch (esc) {
            case '"':
              value += '"';
              break;
            case "\\":
              value += "\\";
              break;
            case "n":
              value += "\n";
              break;
            case "t":
              value += "	";
              break;
            default:
              throw this.error(`Invalid escape sequence \\${esc}`);
          }
          continue;
        }
        if (ch === "\n") {
          throw this.error("Unterminated string literal");
        }
        value += this.advance();
      }
      throw this.error("Unterminated string literal");
    }
    readSymbol() {
      const startCol = this.col;
      const value = this.advance();
      return {
        type: "SYMBOL",
        value,
        line: this.line,
        col: startCol
      };
    }
    readIdentifier() {
      const startCol = this.col;
      let value = "";
      while (!this.isEOF() && this.isIdentPart(this.peek())) {
        value += this.advance();
      }
      if (CONTROL_KEYWORDS.has(value)) {
        return {
          type: "KEYWORD",
          value,
          line: this.line,
          col: startCol
        };
      }
      if (NAMESPACE_KEYWORDS.has(value)) {
        return {
          type: "KEYWORD",
          value,
          line: this.line,
          col: startCol
        };
      }
      return {
        type: "IDENT",
        value,
        line: this.line,
        col: startCol
      };
    }
    readNumber() {
      const startCol = this.col;
      let value = "";
      while (!this.isEOF() && this.isDigit(this.peek())) {
        value += this.advance();
      }
      return {
        type: "NUMBER",
        value,
        line: this.line,
        col: startCol
      };
    }
    skipWhitespace() {
      let skipped = false;
      while (!this.isEOF()) {
        const ch = this.peek();
        if (ch === " " || ch === "	" || ch === "\n" || ch === "\r") {
          this.advance();
          skipped = true;
        } else {
          break;
        }
      }
      return skipped;
    }
    advance() {
      const ch = this.input[this.pos++];
      if (ch === "\n") {
        this.line++;
        this.col = 1;
      } else {
        this.col++;
      }
      return ch;
    }
    peek() {
      return this.input[this.pos];
    }
    peekNext() {
      return this.input[this.pos + 1];
    }
    isEOF() {
      return this.pos >= this.input.length;
    }
    isDigit(ch) {
      return ch >= "0" && ch <= "9";
    }
    isIdentStart(ch) {
      return /[a-zA-Z_]/.test(ch);
    }
    isIdentPart(ch) {
      return /[a-zA-Z0-9_]/.test(ch);
    }
    error(msg) {
      return new Error(`[${this.line}:${this.col}] ${msg}`);
    }
  };

  // src/constructors.ts
  function prompt(params) {
    return { ...params, kind: "prompt" };
  }
  function promptTitle(params) {
    return { ...params, kind: "title" };
  }
  function identifier(params) {
    return { ...params, kind: "identifier" };
  }
  function timeIndex(value) {
    return { kind: "time-index", value };
  }
  function otherIndex(value) {
    return { kind: "other-index", value };
  }
  function chatPromptBody(params) {
    return { ...params, kind: "chat-prompt-body" };
  }
  function completionPromptBody(params) {
    return { ...params, kind: "completion-prompt-body" };
  }
  function noneMessage(params) {
    return { ...params, kind: "none-message" };
  }
  function roleMessage(params) {
    return { ...params, kind: "role-message" };
  }
  function contextVar(params) {
    return { ...params, kind: "context-var" };
  }
  function pathDesc(params) {
    return { ...params, kind: "path-desc" };
  }
  function func(params) {
    return { ...params, kind: "function" };
  }
  function template(params) {
    return { ...params, kind: "template" };
  }
  function loopBlockOutsideRole(params) {
    return { ...params, kind: "loop-block-outside-role" };
  }
  function conditionalBlockOutsideRole(params) {
    return { ...params, kind: "conditional-block-outside-role" };
  }
  function switchBlockOutsideRole(params) {
    return { ...params, kind: "switch-block-outside-role" };
  }
  function caseBlockOutsideRole(params) {
    return { ...params, kind: "case-block-outside-role" };
  }
  function defaultCaseBlockOutsideRole(params) {
    return { ...params, kind: "default-case-block-outside-role" };
  }
  function loopBlockInsideRole(params) {
    return { ...params, kind: "loop-block-inside-role" };
  }
  function conditionalBlockInsideRole(params) {
    return { ...params, kind: "conditional-block-inside-role" };
  }
  function switchBlockInsideRole(params) {
    return { ...params, kind: "switch-block-inside-role" };
  }
  function caseBlockInsideRole(params) {
    return { ...params, kind: "case-block-inside-role" };
  }
  function defaultCaseBlockInsideRole(params) {
    return { ...params, kind: "default-case-block-inside-role" };
  }
  function Iterable(params) {
    return { ...params, kind: "iterable" };
  }
  function rangeExpr(params) {
    return { ...params, kind: "range-expr" };
  }
  function commentBlock(params) {
    return { ...params, kind: "comment-block" };
  }
  function markBlock(params) {
    return { ...params, kind: "mark-block" };
  }
  function markBlockInsideRole(params) {
    return { ...params, kind: "mark-block-inside-role" };
  }
  function arithmeticExpr(params) {
    return { ...params, kind: "arithmetic" };
  }
  function nameDef(params) {
    return { ...params, kind: "name-def" };
  }
  function nameRef(params) {
    return { ...params, kind: "name-ref" };
  }
  function listComprehension(params) {
    return { ...params, kind: "list-comprehension" };
  }
  function endBlock(params) {
    return { ...params, kind: "end-block" };
  }
  function strFragDef(params) {
    return { ...params, kind: "str-frag-def" };
  }
  function rolesFragDef(params) {
    return { ...params, kind: "roles-frag-def" };
  }
  function strFragInvocation(params) {
    return { ...params, kind: "str-frag-invocation" };
  }
  function rolesFragInvocation(params) {
    return { ...params, kind: "roles-frag-invocation" };
  }

  // src/parser.ts
  function toExprToken(tok) {
    return {
      type: tok.type,
      value: tok.value
    };
  }
  var Parser = class {
    constructor(input) {
      __publicField(this, "tokens", []);
      __publicField(this, "pos", 0);
      __publicField(this, "lastConsumedLine", 0);
      const scanner = new Scanner(input);
      let token;
      do {
        token = scanner.nextToken();
        this.tokens.push(token);
      } while (token.type !== "EOF");
    }
    /* ───────────────── Core Navigation ───────────────── */
    peek() {
      return this.tokens[this.pos];
    }
    peekNext() {
      return this.tokens[this.pos + 1];
    }
    /**
     * Consumes a token of a specific type and/or value.
     * Since Token.value is (string | null), we use type assertions for IDENT values.
     */
    consume(type, value) {
      const tok = this.peek();
      if (type && tok.type !== type) {
        throw new Error(`[${tok.line}:${tok.col}] Expected token type ${type}, got ${tok.type} with value ${tok.value}`);
      }
      if (value && tok.value !== value) {
        throw new Error(`[${tok.line}:${tok.col}] Expected value "${value}", got "${tok.value}"`);
      }
      this.pos++;
      this.lastConsumedLine = tok.line;
      return tok;
    }
    match(type, value) {
      const tok = this.peek();
      if (tok.type === type && (!value || tok.value === value)) {
        this.pos++;
        this.lastConsumedLine = tok.line;
        return true;
      }
      return false;
    }
    /* ───────────────── Grammar Rules (Outside Role) ───────────────── */
    /**
     * Entry Point: Prompt[indices]: { ... }
     */
    parsePrompt() {
      const title = this.parseTitle();
      this.consume("SYMBOL", ":");
      this.consume("SYMBOL", "{");
      const body = this.parsePromptBody();
      this.consume("SYMBOL", "}");
      console.log("parsed prompt");
      return prompt({ title, body });
    }
    /**
     * Parse a file containing one or more prompts, fragment definitions, and comments.
     * Returns an array of Prompt, StrFragDef, RolesFragDef, and CommentBlock objects.
     */
    parseFile() {
      const blocks = [];
      while (!this.isEOF()) {
        const tok = this.peek();
        if (tok.type === "COMMENT") {
          const text = this.consume("COMMENT").value;
          blocks.push(commentBlock({ text }));
        } else if (tok.type === "KEYWORD" && tok.value === "StrFrag") {
          blocks.push(this.parseStrFragDef());
        } else if (tok.type === "KEYWORD" && tok.value === "RoleFrag") {
          blocks.push(this.parseRolesFragDef());
        } else if (tok.type === "IDENT") {
          let lookPos = this.pos + 1;
          while (lookPos < this.tokens.length && this.tokens[lookPos].type === "COMMENT") lookPos++;
          const lookTok = this.tokens[lookPos];
          if (lookTok && (lookTok.value === ":" || lookTok.value === "[")) {
            blocks.push(this.parsePrompt());
          } else {
            this.skipBlock();
          }
        } else {
          blocks.push(this.parsePrompt());
        }
      }
      return blocks;
    }
    skipBlock() {
      while (this.peek().type !== "EOF" && this.peek().value !== "{") {
        this.pos++;
      }
      if (this.peek().value === "{") {
        this.pos++;
        let depth = 1;
        while (this.peek().type !== "EOF" && depth > 0) {
          if (this.peek().value === "{") depth++;
          if (this.peek().value === "}") depth--;
          this.pos++;
        }
      }
    }
    /**
     * Parse a StrFrag definition: StrFrag Name[params]: { RoleBuildingBlock* }
     */
    parseStrFragDef() {
      this.consume("KEYWORD", "StrFrag");
      const name = this.consume("IDENT").value;
      let params = [];
      if (this.peek().value === "[") {
        this.consume("SYMBOL", "[");
        if (this.peek().value !== "]") {
          params = this.parseTextArgs();
        }
        this.consume("SYMBOL", "]");
      }
      this.consume("SYMBOL", ":");
      this.consume("SYMBOL", "{");
      const body = [];
      while (this.peek().type !== "EOF" && this.peek().value !== "}") {
        body.push(this.parseRoleBuildingBlock());
      }
      this.consume("SYMBOL", "}");
      console.log("parsed StrFrag definition");
      return strFragDef({ name, params, body });
    }
    /**
     * Parse a RoleFrag definition: RoleFrag Name[params]: { PromptBlock* }
     */
    parseRolesFragDef() {
      this.consume("KEYWORD", "RoleFrag");
      const name = this.consume("IDENT").value;
      let params = [];
      if (this.peek().value === "[") {
        this.consume("SYMBOL", "[");
        if (this.peek().value !== "]") {
          params = this.parseTextArgs();
        }
        this.consume("SYMBOL", "]");
      }
      this.consume("SYMBOL", ":");
      this.consume("SYMBOL", "{");
      const body = [];
      while (this.peek().type !== "EOF" && this.peek().value !== "}") {
        if (this.peek().type === "COMMENT") {
          const text = this.consume("COMMENT").value;
          body.push(commentBlock({ text }));
          continue;
        }
        body.push(this.parsePromptBodyItem());
      }
      this.consume("SYMBOL", "}");
      console.log("parsed RoleFrag definition");
      return rolesFragDef({ name, params, body });
    }
    parseTitle() {
      const name = this.consume("IDENT").value;
      const indices = this.parseOptionalIndices();
      console.log("parsed title");
      return promptTitle({ name, indices });
    }
    /**
     * Gatekeeper for Top-Level Scope.
     * Detects whether this is a chat prompt (multiple roles) or completion prompt (single N: message).
     */
    parsePromptBody() {
      const savedPos = this.pos;
      while (this.peek().type === "COMMENT") {
        this.pos++;
      }
      const isCompletionPrompt = this.peek().type === "IDENT" && this.peek().value === "N";
      this.pos = savedPos;
      if (isCompletionPrompt) {
        return this.parseCompletionPromptBody();
      }
      return this.parseChatPromptBody();
    }
    /**
     * Parse a chat prompt body (standard multi-role format).
     */
    parseChatPromptBody() {
      const body = [];
      while (this.peek().type !== "EOF" && this.peek().value !== "}") {
        if (this.peek().type === "COMMENT") {
          const text = this.consume("COMMENT").value;
          body.push(commentBlock({ text }));
          continue;
        }
        body.push(this.parsePromptBodyItem());
      }
      const comment = this.parseOptionalComment();
      return chatPromptBody({ body });
    }
    /**
     * Parse a completion prompt body (single N: message, no other roles allowed).
     */
    parseCompletionPromptBody() {
      while (this.peek().type === "COMMENT") {
        this.consume("COMMENT");
      }
      const message = this.parseNoneMessage();
      while (this.peek().type === "COMMENT") {
        this.consume("COMMENT");
      }
      if (this.peek().type !== "EOF" && this.peek().value !== "}") {
        const tok = this.peek();
        throw new Error(`[${tok.line}:${tok.col}] Completion prompts (N:) can only have a single message. Found unexpected token "${tok.value}"`);
      }
      return completionPromptBody({ message });
    }
    /**
     * Parse a NoneMessage: N: { RoleBuildingBlock* }
     */
    parseNoneMessage() {
      this.consume("IDENT", "N");
      this.consume("SYMBOL", ":");
      const body = [];
      if (this.peek().value === "{") {
        this.consume("SYMBOL", "{");
        while (this.peek().type !== "EOF" && this.peek().value !== "}") {
          body.push(this.parseRoleBuildingBlock());
        }
        this.consume("SYMBOL", "}");
      } else {
        const startLine = this.peek().line;
        body.push(this.parseRoleBuildingBlockSingleLine(startLine));
      }
      return noneMessage({ body });
    }
    /**
     * Parse a PromptBodyItem (either a PromptBlock or a LabelBlock).
     */
    parsePromptBodyItem() {
      return this.parseTopLevelBlock();
    }
    parseTopLevelBlock() {
      const tok = this.peek();
      const nextTok = this.peekNext();
      const val = tok.value;
      if (tok.type === "IDENT" && (val === "S" || val === "U" || val === "A" || val === "T")) {
        console.log("parsing role message");
        return this.parseRoleMessage();
      }
      if (tok.type === "KEYWORD") {
        switch (val) {
          case "If":
            return this.parseConditionalOutside();
          case "ForEach":
            return this.parseLoopOutside();
          case "Switch":
            return this.parseSwitchOutside();
          case "Name":
            return this.parseNameDef();
          case "Mark":
            return this.parseMarkBlock();
          case "Frag":
            return this.parseRolesFragInvocation();
          default:
            this.skipBlock();
            return commentBlock({ text: "" });
        }
      }
      if (tok.type === "IDENT" && val === "PromptEndsHere") {
        return this.parseEndBlock();
      }
      if (tok.type === "COMMENT") {
        const text = this.consume("COMMENT").value;
        return commentBlock({ text });
      }
      if (tok.type === "IDENT") {
        let lookPos = this.pos + 1;
        let foundBrace = false;
        for (let i = 0; i < 6 && lookPos < this.tokens.length; i++, lookPos++) {
          if (this.tokens[lookPos].value === "{") {
            foundBrace = true;
            break;
          }
        }
        if (foundBrace) {
          this.skipBlock();
          return commentBlock({ text: "" });
        }
      }
      throw new Error(`[${tok.line}:${tok.col}] Syntax Error: Unexpected token "${val}" in global scope.`);
    }
    /**
     * Parse a MarkBlock: MARK number { PromptBlock+ }
     * Mark blocks are like label blocks but rendered with a bracket on the right.
     */
    parseMarkBlock() {
      this.consume("KEYWORD", "Mark");
      const numberTok = this.consume("NUMBER");
      const markNumber = parseInt(numberTok.value, 10);
      this.consume("SYMBOL", "{");
      const blocks = [];
      do {
        if (this.peek().type === "COMMENT") {
          const text = this.consume("COMMENT").value;
          blocks.push(commentBlock({ text }));
          continue;
        }
        const innerBlock = this.parseTopLevelBlock();
        blocks.push(innerBlock);
      } while (this.peek().value !== "}");
      this.consume("SYMBOL", "}");
      return markBlock({ markNumber, body: blocks });
    }
    /**
     * Parse a MarkBlockInsideRole: MARK number { RoleBuildingBlock+ }
     * Mark blocks inside roles contain role building blocks.
     */
    parseMarkBlockInside() {
      this.consume("KEYWORD", "Mark");
      const numberTok = this.consume("NUMBER");
      const markNumber = parseInt(numberTok.value, 10);
      this.consume("SYMBOL", "{");
      const blocks = [];
      do {
        if (this.peek().type === "COMMENT") {
          const text = this.consume("COMMENT").value;
          blocks.push(commentBlock({ text }));
          continue;
        }
        const innerBlock = this.parseRoleBuildingBlock();
        blocks.push(innerBlock);
      } while (this.peek().value !== "}");
      this.consume("SYMBOL", "}");
      return markBlockInsideRole({ markNumber, body: blocks });
    }
    /*
     * RoleMessage = ROLE_ID: { RoleBuildingBlock* } | ROLE_ID: RoleBuildingBlock
     * Supports both multi-line blocks with curly braces and single-line without braces
    */
    parseRoleMessage() {
      const roleId = this.consume("IDENT").value;
      this.consume("SYMBOL", ":");
      const roleMap = { "S": "system", "U": "user", "A": "assistant", "T": "tool" };
      const role = roleMap[roleId];
      const body = [];
      if (this.peek().value === "{") {
        this.consume("SYMBOL", "{");
        while (this.peek().type !== "EOF" && this.peek().value !== "}") {
          body.push(this.parseRoleBuildingBlock());
        }
        this.consume("SYMBOL", "}");
      } else {
        const startLine = this.peek().line;
        body.push(this.parseRoleBuildingBlockSingleLine(startLine));
      }
      return roleMessage({ role, body });
    }
    /* ───────────────── Grammar Rules (Inside Role) ───────────────── */
    /**
    * Parse a single RoleBuildingBlock that must stay on the same line.
    * Used for single-line role syntax (e.g., U: obs.user_query[@i])
    */
    parseRoleBuildingBlockSingleLine(startLine) {
      const tok = this.peek();
      if (tok.line !== startLine) {
        throw new Error(`[${tok.line}:${tok.col}] Single-line role syntax cannot span multiple lines`);
      }
      const val = tok.value;
      if (tok.type === "KEYWORD") {
        if (val === "If" || val === "ForEach" || val === "Switch") {
          throw new Error(`[${tok.line}:${tok.col}] Control flow statements not allowed in single-line role syntax`);
        }
        const namespaces = ["env", "sys", "resp", "prompt"];
        if (namespaces.includes(val)) {
          return this.parseContextVar();
        }
      }
      if (tok.type === "IDENT") return this.parseTemplateOrFunc();
      throw new Error(`[${tok.line}:${tok.col}] Unexpected ${tok.type} (${val}) in single-line role syntax`);
    }
    /**
     * Gatekeeper for Inside-Role Scope.
     * Strictly collects RoleBuildingBlocks (ContextVars, Templates, Logic).
     */
    parseRoleBuildingBlock() {
      const tok = this.peek();
      const val = tok.value;
      console.log("started role building block");
      if (tok.type === "COMMENT") {
        const text = this.consume("COMMENT").value;
        return commentBlock({ text });
      }
      if (tok.type === "SYMBOL" && val === "$") {
        return this.parseNameRef();
      }
      if (tok.type === "KEYWORD") {
        if (val === "If") return this.parseConditionalInside();
        if (val === "ForEach") return this.parseLoopInside();
        if (val === "Switch") return this.parseSwitchInside();
        if (val === "Mark") return this.parseMarkBlockInside();
        if (val === "Name") return this.parseNameDef();
        if (val === "Frag") return this.parseStrFragInvocation();
        if (val === "break" || val === "continue") {
          const name = this.consume("KEYWORD").value;
          return template({ name, arguments: [], comment: void 0 });
        }
        const namespaces = ["env", "sys", "resp", "prompt"];
        if (namespaces.includes(val)) {
          return this.parseContextVar();
        }
      }
      if (tok.type === "IDENT" && val === "PromptEndsHere") {
        return this.parseEndBlock();
      }
      if (tok.type === "IDENT") return this.parseTemplateOrFunc();
      if (tok.type === "STRING") {
        const name = this.consume("STRING").value;
        return template({ name, arguments: [], comment: void 0 });
      }
      throw new Error(`[${tok.line}:${tok.col}] Unexpected ${tok.type} (${val}) inside role.`);
    }
    /* ───────────────── Name Definitions ───────────────── */
    /**
     * Parse a name definition: name varname := expr
     * where expr is a ContextVar, Func, ListComprehension, or StrFragInvocation
     */
    parseNameDef() {
      this.consume("KEYWORD", "Name");
      const varName = this.consume("IDENT").value;
      this.consume("SYMBOL", ":");
      this.consume("LOGIC_OP", "=");
      const tok = this.peek();
      let value;
      if (tok.type === "SYMBOL" && tok.value === "[") {
        value = this.parseListComprehension();
      } else if (tok.type === "KEYWORD" && ["env", "sys", "resp", "prompt"].includes(tok.value)) {
        value = this.parseContextVar();
      } else if (tok.type === "KEYWORD" && tok.value === "Frag") {
        value = this.parseStrFragInvocation();
      } else if (tok.type === "IDENT") {
        const parsed = this.parseTemplateOrFunc();
        if (parsed.kind !== "function") {
          const parsedName = parsed.kind === "template" ? parsed.name : "identifier";
          throw new Error(`[${tok.line}:${tok.col}] name definitions require a ContextVar, Func, list comprehension, or Frag invocation, got ${parsed.kind} "${parsedName}"`);
        }
        value = parsed;
      } else {
        throw new Error(`[${tok.line}:${tok.col}] Expected ContextVar, Func, list comprehension, or Frag invocation after :=, got ${tok.type}`);
      }
      return nameDef({ name: varName, value });
    }
    /**
     * Parse a list comprehension: [expr for var in iterable]
     * Example: [sys.Summary[@t] for t in range(T, T-900, 100)]
     */
    parseListComprehension() {
      this.consume("SYMBOL", "[");
      const elemTok = this.peek();
      let element;
      if (elemTok.type === "KEYWORD" && ["env", "sys", "resp", "prompt"].includes(elemTok.value)) {
        element = this.parseContextVar();
      } else if (elemTok.type === "KEYWORD" && elemTok.value === "Frag") {
        element = this.parseStrFragInvocation();
      } else if (elemTok.type === "IDENT") {
        const parsed = this.parseTemplateOrFunc();
        if (parsed.kind !== "function") {
          const parsedName = parsed.kind === "template" ? parsed.name : "identifier";
          throw new Error(`[${elemTok.line}:${elemTok.col}] List comprehension element must be ContextVar, Func, or Frag invocation, got ${parsed.kind} "${parsedName}"`);
        }
        element = parsed;
      } else {
        throw new Error(`[${elemTok.line}:${elemTok.col}] Expected ContextVar, Func, or Frag invocation in list comprehension, got ${elemTok.type}`);
      }
      this.consume("KEYWORD", "for");
      const variable = this.consume("IDENT").value;
      this.consume("KEYWORD", "in");
      let iterable;
      if (this.peek().value === "range" && this.peekNext().value === "(") {
        iterable = this.parseRangeExpr();
      } else {
        const iterTokens = [];
        while (this.peek().value !== "]") {
          if (this.isEOF()) throw new Error("Unterminated list comprehension");
          iterTokens.push(toExprToken(this.consume()));
        }
        iterable = Iterable({ tokens: iterTokens });
      }
      this.consume("SYMBOL", "]");
      return listComprehension({ element, variable, iterable });
    }
    /**
     * Parse a name reference: $varname with optional indices and path: $docs[i].content
     */
    parseNameRef() {
      this.consume("SYMBOL", "$");
      const varName = this.consume("IDENT").value;
      const indices = this.parseOptionalIndices();
      let path2;
      if (this.match("SYMBOL", ".")) {
        path2 = this.parsePathDesc();
      }
      return nameRef({ name: varName, indices, path: path2 });
    }
    /* ───────────────── Fragment Invocations ───────────────── */
    /**
     * Parse a StrFrag invocation: Frag FragName[args]
     * Used inside role bodies where StrFragInvocation is valid.
     */
    parseStrFragInvocation() {
      this.consume("KEYWORD", "Frag");
      const name = this.consume("IDENT").value;
      let args = [];
      if (this.peek().value === "[") {
        this.consume("SYMBOL", "[");
        if (this.peek().value !== "]") {
          args = this.parseTextArgs();
        }
        this.consume("SYMBOL", "]");
      }
      return strFragInvocation({ name, arguments: args });
    }
    /**
     * Parse a RolesFrag invocation: Frag FragName[args]
     * Used at top level where RolesFragInvocation is valid.
     */
    parseRolesFragInvocation() {
      this.consume("KEYWORD", "Frag");
      const name = this.consume("IDENT").value;
      let args = [];
      if (this.peek().value === "[") {
        this.consume("SYMBOL", "[");
        if (this.peek().value !== "]") {
          args = this.parseTextArgs();
        }
        this.consume("SYMBOL", "]");
      }
      return rolesFragInvocation({ name, arguments: args });
    }
    /* ───────────────── Expressions & Shared Rules ───────────────── */
    parseContextVar() {
      const baseTok = this.consume("KEYWORD");
      const base = baseTok.value;
      const indices = this.parseOptionalIndices();
      let path2;
      if (this.match("SYMBOL", ".")) {
        path2 = this.parsePathDesc();
      }
      const nextTok = this.peek();
      const comment = nextTok.type === "COMMENT" && nextTok.line === this.lastConsumedLine ? this.consume("COMMENT").value : void 0;
      return contextVar({ base, indices, path: path2, comment });
    }
    parsePathDesc() {
      const tok = this.peek();
      console.log(`parsePathDesc: tok=${tok.type}:${tok.value} at ${tok.line}:${tok.col}`);
      if (tok.type !== "IDENT" && tok.type !== "KEYWORD" && tok.type !== "NUMBER") {
        throw new Error(`[${tok.line}:${tok.col}] Expected identifier or number in path, got ${tok.type}`);
      }
      const base = this.consume().value;
      console.log(`parsePathDesc: base=${base}, about to parse indices`);
      const indices = this.parseOptionalIndices();
      console.log(`parsePathDesc: after indices, peek=${this.peek().type}:${this.peek().value}`);
      let next;
      if (this.match("SYMBOL", ".")) {
        console.log(`parsePathDesc: matched dot, recursing`);
        next = this.parsePathDesc();
      }
      return pathDesc({ base, indices, next });
    }
    parseTemplateOrFunc() {
      const name = this.consume("IDENT").value;
      if (name === name.toUpperCase()) {
        let args = [];
        if (this.peek().value === "(") {
          this.consume("SYMBOL", "(");
          args = this.parseTextArgs();
          this.consume("SYMBOL", ")");
        }
        const nextTok = this.peek();
        const comment = nextTok.type === "COMMENT" && nextTok.line === this.lastConsumedLine ? this.consume("COMMENT").value : void 0;
        return template({ name, arguments: args, comment });
      }
      if (this.peek().value === "(") {
        this.consume("SYMBOL", "(");
        const args = this.parseTextArgs();
        this.consume("SYMBOL", ")");
        const indices = this.parseOptionalIndices();
        const nextTok = this.peek();
        const comment = nextTok.type === "COMMENT" && nextTok.line === this.lastConsumedLine ? this.consume("COMMENT").value : void 0;
        return func({ name, arguments: args, indices, comment });
      }
      let path2;
      if (this.match("SYMBOL", ".")) {
        path2 = this.parsePathDesc();
      }
      return otherIndex(identifier({ name, path: path2 }));
    }
    parseTextArgs() {
      const args = [];
      if (this.peek().value === ")" || this.peek().value === "]") return args;
      do {
        const arg = this.parseSingleTextArg();
        args.push(arg);
      } while (this.match("SYMBOL", ","));
      return args;
    }
    /** Parse a single argument, which may be an arithmetic expression */
    parseSingleTextArg() {
      let left = this.parseAtom();
      if (this.peek().type === "ARITH_OP") {
        const operators = [];
        while (this.peek().type === "ARITH_OP") {
          operators.push(this.consume("ARITH_OP").value);
        }
        const right = this.parseSingleTextArg();
        return arithmeticExpr({ operator: operators, left, right });
      }
      return left;
    }
    /** Parse an atomic value: number, time index, context var, name ref, or function/identifier */
    parseAtom() {
      const tok = this.peek();
      if (this.match("SYMBOL", "@")) {
        return timeIndex(this.parseIndexValue());
      }
      if (tok.type === "SYMBOL" && tok.value === "$") {
        return this.parseNameRef();
      }
      if (tok.type === "KEYWORD" && ["env", "sys", "resp", "prompt"].includes(tok.value)) {
        return this.parseContextVar();
      }
      if (tok.type === "KEYWORD" && tok.value === "Frag") {
        return this.parseStrFragInvocation();
      }
      if (tok.type === "NUMBER") {
        const name = this.consume("NUMBER").value;
        let path2;
        if (this.match("SYMBOL", ".")) {
          path2 = this.parsePathDesc();
        }
        return identifier({ name, path: path2 });
      }
      if (tok.type === "IDENT") {
        if (this.peekNext().value === "(") {
          return this.parseTemplateOrFunc();
        }
        const name = this.consume("IDENT").value;
        let path2;
        if (this.match("SYMBOL", ".")) {
          path2 = this.parsePathDesc();
        }
        return otherIndex(identifier({ name, path: path2 }));
      }
      throw new Error(`[${tok.line}:${tok.col}] Unexpected token in arguments: ${tok.type} (${tok.value})`);
    }
    parseOptionalIndices() {
      const indices = [];
      console.log(`parseOptionalIndices: peek=${this.peek().type}:${this.peek().value}`);
      while (this.match("SYMBOL", "[")) {
        console.log(`parseOptionalIndices: found [, parsing index`);
        indices.push(this.parseIndex());
        console.log(`parseOptionalIndices: after parseIndex, peek=${this.peek().type}:${this.peek().value}`);
        while (this.match("SYMBOL", ",")) {
          indices.push(this.parseIndex());
        }
        console.log(`parseOptionalIndices: consuming ], peek=${this.peek().type}:${this.peek().value}`);
        this.consume("SYMBOL", "]");
      }
      console.log(`parseOptionalIndices: returning ${indices.length} indices, peek=${this.peek().type}:${this.peek().value}`);
      return indices;
    }
    parseIndex() {
      console.log(`parseIndex: starting, peek=${this.peek().type}:${this.peek().value}`);
      const time = this.match("SYMBOL", "@");
      console.log(`parseIndex: time=${time}, peek after @check=${this.peek().type}:${this.peek().value}`);
      const value = this.parseIndexValue();
      console.log(`parseIndex: returning ${time ? "time" : "other"}-index`);
      if (time) {
        return timeIndex(value);
      } else {
        return otherIndex(value);
      }
    }
    /**
     * Parse the value inside an index bracket.
     * Can be: ContextVar, Func, Identifier, ArithmeticExpr, NameRef
     */
    parseIndexValue() {
      let left = this.parseIndexAtom();
      if (this.peek().type === "ARITH_OP") {
        const operators = [];
        while (this.peek().type === "ARITH_OP") {
          operators.push(this.consume("ARITH_OP").value);
        }
        const right = this.parseIndexValue();
        return arithmeticExpr({ operator: operators, left, right });
      }
      return left;
    }
    /**
     * Parse an atomic value inside an index (without arithmetic).
     */
    parseIndexAtom() {
      const tok = this.peek();
      if (tok.type === "SYMBOL" && tok.value === "$") {
        return this.parseNameRef();
      }
      if (tok.type === "KEYWORD" && ["sys", "env", "resp", "prompt"].includes(tok.value)) {
        return this.parseContextVar();
      }
      if (tok.type === "NUMBER") {
        const name = this.consume("NUMBER").value;
        let path2;
        if (this.match("SYMBOL", ".")) {
          path2 = this.parsePathDesc();
        }
        return identifier({ name, path: path2 });
      }
      if (tok.type === "IDENT") {
        const name = this.consume("IDENT").value;
        if (this.peek().value === "(") {
          this.consume("SYMBOL", "(");
          const args = this.parseTextArgs();
          this.consume("SYMBOL", ")");
          const indices = this.parseOptionalIndices();
          return func({ name, arguments: args, indices });
        }
        let path2;
        if (this.match("SYMBOL", ".")) {
          path2 = this.parsePathDesc();
        }
        return identifier({ name, path: path2 });
      }
      throw new Error(`[${tok.line}:${tok.col}] Unexpected token in index: ${tok.type} (${tok.value})`);
    }
    /* ───────────────── Control Flow ───────────────── */
    /**
     * Parse an END block: PromptEndsHere when (condition)
     * Conditional early termination that can appear anywhere.
     * Condition is delimited by parentheses, same style as conditionals.
     */
    parseEndBlock() {
      this.consume("IDENT", "PromptEndsHere");
      this.consume("KEYWORD", "when");
      this.consume("SYMBOL", "(");
      const conditionTokens = [];
      let depth = 1;
      while (depth > 0) {
        if (this.isEOF()) throw new Error("Unterminated PromptEndsHere when condition");
        const tok = this.consume();
        if (tok.value === "(") depth++;
        if (tok.value === ")") depth--;
        if (depth > 0) {
          conditionTokens.push(toExprToken(tok));
        }
      }
      return endBlock({ condition: conditionTokens });
    }
    parseLoopOutside() {
      this.consume("KEYWORD", "ForEach");
      this.consume("SYMBOL", "(");
      const index = this.parseIndex();
      this.consume("SYMBOL", ":");
      let iterable;
      if (this.peek().value === "range" && this.peekNext().value === "(") {
        iterable = this.parseRangeExpr();
      } else {
        const iterTokens = [];
        while (!(this.peek().value === ")" && this.peekNext().value === "{")) {
          if (this.isEOF()) throw new Error("Unterminated ForEach iterable");
          iterTokens.push(toExprToken(this.consume()));
        }
        iterable = Iterable({ tokens: iterTokens });
      }
      this.consume("SYMBOL", ")");
      this.consume("SYMBOL", "{");
      const body = [];
      while (this.peek().value !== "}") {
        body.push(this.parseTopLevelBlock());
      }
      this.consume("SYMBOL", "}");
      return loopBlockOutsideRole({ index, iterable, body });
    }
    parseRangeExpr() {
      this.consume("IDENT", "range");
      this.consume("SYMBOL", "(");
      const start = [];
      let depth = 0;
      while (!(this.peek().value === "," && depth === 0)) {
        if (this.isEOF()) throw new Error("Unterminated range expression");
        const tok = this.consume();
        if (tok.value === "(") depth++;
        if (tok.value === ")") depth--;
        start.push(toExprToken(tok));
      }
      this.consume("SYMBOL", ",");
      const end = [];
      depth = 0;
      while (!((this.peek().value === "," || this.peek().value === ")") && depth === 0)) {
        if (this.isEOF()) throw new Error("Unterminated range expression");
        const tok = this.consume();
        if (tok.value === "(") depth++;
        if (tok.value === ")") depth--;
        end.push(toExprToken(tok));
      }
      let step;
      if (this.peek().value === ",") {
        this.consume("SYMBOL", ",");
        step = [];
        depth = 0;
        while (!(this.peek().value === ")" && depth === 0)) {
          if (this.isEOF()) throw new Error("Unterminated range expression");
          const tok = this.consume();
          if (tok.value === "(") depth++;
          if (tok.value === ")") depth--;
          step.push(toExprToken(tok));
        }
      }
      this.consume("SYMBOL", ")");
      return rangeExpr({ start, end, step });
    }
    parseConditionalOutside() {
      this.consume("KEYWORD", "If");
      const ifCondTokens = [];
      while (this.peek().value !== "{") {
        if (this.isEOF()) throw new Error("Unterminated If condition");
        ifCondTokens.push(toExprToken(this.consume()));
      }
      this.consume("SYMBOL", "{");
      const ifBody = [];
      while (this.peek().value !== "}") {
        ifBody.push(this.parseTopLevelBlock());
      }
      this.consume("SYMBOL", "}");
      const elseIfConditions = [];
      const elseIfBodies = [];
      let elseBody = void 0;
      while (this.peek().type === "KEYWORD" && (this.peek().value === "ElseIf" || this.peek().value === "Else")) {
        const type = this.consume().value;
        if (type === "ElseIf") {
          const eiCondTokens = [];
          while (this.peek().value !== "{") {
            eiCondTokens.push(toExprToken(this.consume()));
          }
          this.consume("SYMBOL", "{");
          const eiBody = [];
          while (this.peek().value !== "}") {
            eiBody.push(this.parseTopLevelBlock());
          }
          this.consume("SYMBOL", "}");
          elseIfConditions.push(eiCondTokens);
          elseIfBodies.push(eiBody);
        } else if (type === "Else") {
          this.consume("SYMBOL", "{");
          const eBody = [];
          while (this.peek().value !== "}") {
            eBody.push(this.parseTopLevelBlock());
          }
          this.consume("SYMBOL", "}");
          elseBody = eBody;
          break;
        }
      }
      return conditionalBlockOutsideRole({
        Ifcondition: ifCondTokens,
        IfBody: ifBody,
        elseif: elseIfConditions,
        elseifBody: elseIfBodies,
        elseBody
      });
    }
    parseLoopInside() {
      this.consume("KEYWORD", "ForEach");
      this.consume("SYMBOL", "(");
      const index = this.parseIndex();
      this.consume("SYMBOL", ":");
      let iterable;
      if (this.peek().value === "range" && this.peekNext().value === "(") {
        iterable = this.parseRangeExpr();
      } else {
        const iterTokens = [];
        while (!(this.peek().value === ")" && this.peekNext().value === "{")) {
          if (this.isEOF()) throw new Error("Unterminated ForEach iterable");
          iterTokens.push(toExprToken(this.consume()));
        }
        iterable = Iterable({ tokens: iterTokens });
      }
      this.consume("SYMBOL", ")");
      this.consume("SYMBOL", "{");
      const body = [];
      while (this.peek().value !== "}") body.push(this.parseRoleBuildingBlock());
      this.consume("SYMBOL", "}");
      return loopBlockInsideRole({ index, iterable, body });
    }
    parseConditionalInside() {
      this.consume("KEYWORD", "If");
      const ifCondTokens = [];
      while (this.peek().value !== "{") {
        if (this.isEOF()) throw new Error("Unterminated If condition");
        ifCondTokens.push(toExprToken(this.consume()));
      }
      this.consume("SYMBOL", "{");
      const ifBody = [];
      while (this.peek().value !== "}") {
        ifBody.push(this.parseRoleBuildingBlock());
      }
      this.consume("SYMBOL", "}");
      const elseIfConditions = [];
      const elseIfBodies = [];
      let elseBody = void 0;
      while (this.peek().type === "KEYWORD" && (this.peek().value === "ElseIf" || this.peek().value === "Else")) {
        const type = this.consume().value;
        if (type === "ElseIf") {
          const eiCondTokens = [];
          while (this.peek().value !== "{") {
            eiCondTokens.push(toExprToken(this.consume()));
          }
          this.consume("SYMBOL", "{");
          const eiBody = [];
          while (this.peek().value !== "}") {
            eiBody.push(this.parseRoleBuildingBlock());
          }
          this.consume("SYMBOL", "}");
          elseIfConditions.push(eiCondTokens);
          elseIfBodies.push(eiBody);
        } else if (type === "Else") {
          this.consume("SYMBOL", "{");
          const eBody = [];
          while (this.peek().value !== "}") {
            eBody.push(this.parseRoleBuildingBlock());
          }
          this.consume("SYMBOL", "}");
          elseBody = eBody;
          break;
        }
      }
      return conditionalBlockInsideRole({
        Ifcondition: ifCondTokens,
        IfBody: ifBody,
        elseif: elseIfConditions,
        elseifBody: elseIfBodies,
        elseBody
      });
    }
    // parseSwitchOutside and parseSwitchInside would follow the same scoping pattern.
    parseSwitchOutside() {
      this.consume("KEYWORD", "Switch");
      const exprTokens = [];
      while (this.peek().value !== "{") {
        if (this.isEOF()) throw new Error("Expected '{' after Switch expression");
        exprTokens.push(toExprToken(this.consume()));
      }
      this.consume("SYMBOL", "{");
      const cases = [];
      let defaultCase;
      while (this.peek().value !== "}") {
        const kw = this.consume("KEYWORD").value;
        if (kw === "Case") {
          const matchTokens = [];
          while (this.peek().value !== "{") {
            if (this.isEOF()) throw new Error("Expected '{' after Case match");
            matchTokens.push(toExprToken(this.consume()));
          }
          this.consume("SYMBOL", "{");
          const body = [];
          while (this.peek().value !== "}") {
            body.push(this.parseTopLevelBlock());
          }
          this.consume("SYMBOL", "}");
          cases.push(caseBlockOutsideRole({ match: matchTokens, body }));
        } else if (kw === "Default") {
          this.consume("SYMBOL", "{");
          const body = [];
          while (this.peek().value !== "}") {
            body.push(this.parseTopLevelBlock());
          }
          this.consume("SYMBOL", "}");
          defaultCase = defaultCaseBlockOutsideRole({ body });
        }
      }
      this.consume("SYMBOL", "}");
      return switchBlockOutsideRole({
        expression: exprTokens,
        cases,
        defaultCase
      });
    }
    parseSwitchInside() {
      this.consume("KEYWORD", "Switch");
      const exprTokens = [];
      while (this.peek().value !== "{") {
        if (this.isEOF()) throw new Error("Expected '{' after Switch expression");
        exprTokens.push(toExprToken(this.consume()));
      }
      this.consume("SYMBOL", "{");
      const cases = [];
      let defaultCase;
      while (this.peek().value !== "}") {
        const kw = this.consume("KEYWORD").value;
        if (kw === "Case") {
          const matchTokens = [];
          while (this.peek().value !== "{") {
            if (this.isEOF()) throw new Error("Expected '{' after Case match");
            matchTokens.push(toExprToken(this.consume()));
          }
          this.consume("SYMBOL", "{");
          const body = [];
          while (this.peek().value !== "}") {
            body.push(this.parseRoleBuildingBlock());
          }
          this.consume("SYMBOL", "}");
          cases.push(caseBlockInsideRole({ match: matchTokens, body }));
        } else if (kw === "Default") {
          this.consume("SYMBOL", "{");
          const body = [];
          while (this.peek().value !== "}") {
            body.push(this.parseRoleBuildingBlock());
          }
          this.consume("SYMBOL", "}");
          defaultCase = defaultCaseBlockInsideRole({ body });
        }
      }
      this.consume("SYMBOL", "}");
      return switchBlockInsideRole({
        expression: exprTokens,
        cases,
        defaultCase
      });
    }
    parseOptionalComment() {
      if (this.peek().type === "COMMENT") {
        return this.consume("COMMENT").value;
      }
      return void 0;
    }
    isEOF() {
      return this.peek().type === "EOF";
    }
  };

  // src/renderPrompt.ts
  function wrapBlock(cls, headerHtml, bodyHtml) {
    return `
<div class="${cls}">
  <div class="${cls}-header">${headerHtml}</div>
  <div class="block-children">
    ${bodyHtml}
  </div>
</div>`;
  }
  function renderPrompt(prompt2, style = "default") {
    const titleHtml = renderPromptTitle(prompt2.title);
    const bodyHtml = renderPromptBody(prompt2.body);
    return `<div class="prompt-container prompt-style-${style}">${titleHtml}${bodyHtml}</div>`;
  }
  function renderPrompts(blocks, style = "default") {
    const parts = [];
    let lastWasDefinition = false;
    for (const block of blocks) {
      if (block.kind === "prompt") {
        if (lastWasDefinition) {
          parts.push('<div class="prompt-divider"></div>');
        }
        parts.push(renderPrompt(block, style));
        lastWasDefinition = true;
      } else if (block.kind === "str-frag-def") {
        if (lastWasDefinition) {
          parts.push('<div class="prompt-divider"></div>');
        }
        parts.push(renderStrFragDef(block, style));
        lastWasDefinition = true;
      } else if (block.kind === "roles-frag-def") {
        if (lastWasDefinition) {
          parts.push('<div class="prompt-divider"></div>');
        }
        parts.push(renderRolesFragDef(block, style));
        lastWasDefinition = true;
      } else if (block.kind === "comment-block") {
        parts.push(`<div class="file-comment">// ${escapeHtml(block.text)}</div>`);
        lastWasDefinition = false;
      }
    }
    return parts.join("");
  }
  function escapeHtml(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function renderExpressionTokens(tokens) {
    const result = [];
    let i = 0;
    const pushContent = (html) => {
      result.push(html);
    };
    while (i < tokens.length) {
      const tok = tokens[i];
      if (tok.type === "KEYWORD" && ["env", "sys", "resp", "prompt"].includes(tok.value) && i + 1 < tokens.length && tokens[i + 1].type === "SYMBOL" && tokens[i + 1].value === ".") {
        const contextVarTokens = [tok.value];
        i++;
        let parenDepth = 0;
        let bracketDepth = 0;
        while (i < tokens.length) {
          const t = tokens[i];
          if (t.value === "[") {
            if (bracketDepth === 0) {
              contextVarTokens.push('<span class="index-bracket">[');
            } else {
              contextVarTokens.push("[");
            }
            bracketDepth++;
            i++;
            continue;
          }
          if (t.value === "]") {
            bracketDepth--;
            if (bracketDepth === 0) {
              contextVarTokens.push("]</span>");
            } else {
              contextVarTokens.push("]");
            }
            i++;
            if (bracketDepth === 0 && parenDepth === 0) {
              if (i < tokens.length && tokens[i].value === ".") {
                continue;
              }
              break;
            }
            continue;
          }
          if (t.value === "(") {
            if (parenDepth === 0) {
              contextVarTokens.push('<span class="paren-content">(');
            } else {
              contextVarTokens.push("(");
            }
            parenDepth++;
            i++;
            continue;
          }
          if (t.value === ")") {
            parenDepth--;
            if (parenDepth === 0) {
              contextVarTokens.push(")</span>");
            } else {
              contextVarTokens.push(")");
            }
            i++;
            if (bracketDepth === 0 && parenDepth === 0) {
              if (i < tokens.length && tokens[i].value === ".") {
                continue;
              }
              break;
            }
            continue;
          }
          if (t.value === "@" && i + 1 < tokens.length) {
            const nextTok = tokens[i + 1];
            if (nextTok.type === "SYMBOL" && nextTok.value === "$" && i + 2 < tokens.length) {
              const varNameTok = tokens[i + 2];
              if (varNameTok.type === "IDENT") {
                const varName = escapeHtml(varNameTok.value);
                contextVarTokens.push(`<span class="time-index"><span class="at-symbol">@</span><span class="name-ref">${varName}</span></span>`);
                i += 3;
                continue;
              }
            }
            if (nextTok.type === "IDENT" || nextTok.type === "NUMBER") {
              let timeIndexName = escapeHtml(nextTok.value);
              i += 2;
              while (i < tokens.length && tokens[i].value === "." && i + 1 < tokens.length && (tokens[i + 1].type === "IDENT" || tokens[i + 1].type === "NUMBER" || tokens[i + 1].value === "@")) {
                timeIndexName += ".";
                i++;
                if (tokens[i].value === "@") {
                  timeIndexName += "@";
                  i++;
                }
                if (i < tokens.length && (tokens[i].type === "IDENT" || tokens[i].type === "NUMBER")) {
                  timeIndexName += escapeHtml(tokens[i].value);
                  i++;
                }
              }
              contextVarTokens.push(`<span class="time-index"><span class="at-symbol">@</span>${timeIndexName}</span>`);
              continue;
            }
          }
          if (t.value === "$" && i + 1 < tokens.length) {
            const nextTok = tokens[i + 1];
            if (nextTok.type === "IDENT") {
              const varName = escapeHtml(nextTok.value);
              contextVarTokens.push(`<span class="name-ref">${varName}</span>`);
              i += 2;
              continue;
            }
          }
          if (parenDepth > 0 || bracketDepth > 0) {
            contextVarTokens.push(escapeHtml(t.value));
            i++;
            continue;
          }
          if (t.value === "." || t.type === "IDENT" || t.type === "KEYWORD" || t.value === "@" || t.type === "NUMBER") {
            if (t.value === "." && parenDepth === 0 && bracketDepth === 0) {
              contextVarTokens.push(".<wbr>");
            } else {
              contextVarTokens.push(escapeHtml(t.value));
            }
            i++;
            continue;
          }
          break;
        }
        pushContent(`<span class="expr-context-var">${contextVarTokens.join("")}</span>`);
        continue;
      }
      if (tok.type === "IDENT" && tok.value === "range" && i + 1 < tokens.length && tokens[i + 1].value === "(") {
        i++;
        i++;
        const startTokens = [];
        let depth = 0;
        while (i < tokens.length && !(tokens[i].value === "," && depth === 0)) {
          const t = tokens[i];
          if (t.value === "(") depth++;
          if (t.value === ")") depth--;
          startTokens.push(t);
          i++;
        }
        i++;
        const endTokens = [];
        depth = 0;
        while (i < tokens.length && !((tokens[i].value === "," || tokens[i].value === ")") && depth === 0)) {
          const t = tokens[i];
          if (t.value === "(") depth++;
          if (t.value === ")") depth--;
          endTokens.push(t);
          i++;
        }
        let stepTokens;
        if (i < tokens.length && tokens[i].value === ",") {
          i++;
          stepTokens = [];
          depth = 0;
          while (i < tokens.length && !(tokens[i].value === ")" && depth === 0)) {
            const t = tokens[i];
            if (t.value === "(") depth++;
            if (t.value === ")") depth--;
            stepTokens.push(t);
            i++;
          }
        }
        i++;
        const startHtml = renderExpressionTokens(startTokens);
        const endHtml = renderExpressionTokens(endTokens);
        const stepHtml = stepTokens ? `<span class="range-step"><span class="range-keyword">every</span><span class="range-step-value">${renderExpressionTokens(stepTokens)}</span></span>` : "";
        pushContent(`<span class="range-expr"><span class="range-start">${startHtml}</span><span class="range-dots">...</span><span class="range-end">${endHtml}</span>${stepHtml}</span><wbr>`);
        continue;
      }
      if (tok.type === "IDENT" && i + 1 < tokens.length && tokens[i + 1].value === "(") {
        const funcName = escapeHtml(tok.value);
        i++;
        i++;
        const argTokens = [];
        let depth = 1;
        while (i < tokens.length && depth > 0) {
          const t = tokens[i];
          if (t.value === "(") depth++;
          if (t.value === ")") depth--;
          if (depth > 0) {
            argTokens.push(t);
          }
          i++;
        }
        const argsHtml = renderExpressionTokens(argTokens);
        const isBuiltinMath = tok.value === "min" || tok.value === "max";
        if (isBuiltinMath) {
          pushContent(`<span class="builtin-func">${funcName}(${argsHtml})</span><wbr>`);
        } else {
          pushContent(`<span class="func-block"><span class="func-name">${funcName}</span><span class="func-parens">(</span>${argsHtml}<span class="func-parens">)</span></span><wbr>`);
        }
        continue;
      }
      if (tok.type === "LOGIC_OP") {
        let combined = tok.value;
        i++;
        while (i < tokens.length && tokens[i].type === "LOGIC_OP") {
          combined += tokens[i].value;
          i++;
        }
        const isConnective = combined === "&&" || combined === "||" || combined === "&" || combined === "|";
        const className = isConnective ? "expr-connective" : "expr-logic-op";
        pushContent(`<span class="${className}">${escapeHtml(combined)}</span>`);
        continue;
      }
      if (tok.type === "SYMBOL" && tok.value === "@" && i + 1 < tokens.length) {
        const nextTok = tokens[i + 1];
        if (nextTok.type === "SYMBOL" && nextTok.value === "$" && i + 2 < tokens.length) {
          const varNameTok = tokens[i + 2];
          if (varNameTok.type === "IDENT") {
            const varName = escapeHtml(varNameTok.value);
            pushContent(`<span class="time-index"><span class="at-symbol">@</span><span class="name-ref">${varName}</span></span>`);
            i += 3;
            continue;
          }
        }
        if (nextTok.type === "IDENT" || nextTok.type === "NUMBER") {
          let timeIndexName = escapeHtml(nextTok.value);
          i += 2;
          while (i < tokens.length && tokens[i].value === "." && i + 1 < tokens.length && (tokens[i + 1].type === "IDENT" || tokens[i + 1].type === "NUMBER" || tokens[i + 1].value === "@")) {
            timeIndexName += ".";
            i++;
            if (tokens[i].value === "@") {
              timeIndexName += "@";
              i++;
            }
            if (i < tokens.length && (tokens[i].type === "IDENT" || tokens[i].type === "NUMBER")) {
              timeIndexName += escapeHtml(tokens[i].value);
              i++;
            }
          }
          pushContent(`<span class="time-index"><span class="at-symbol">@</span>${timeIndexName}</span>`);
          continue;
        }
      }
      if (tok.type === "SYMBOL" && tok.value === "$" && i + 1 < tokens.length) {
        const nextTok = tokens[i + 1];
        if (nextTok.type === "IDENT") {
          const varName = escapeHtml(nextTok.value);
          pushContent(`<span class="name-ref">${varName}</span>`);
          i += 2;
          continue;
        }
      }
      const escaped = escapeHtml(tok.value);
      switch (tok.type) {
        case "KEYWORD":
          if (tok.value === "and" || tok.value === "or") {
            pushContent(`<span class="expr-keyword">${escaped}</span>`);
          } else {
            pushContent(`<span class="keyword">${escaped}</span>`);
          }
          break;
        case "IDENT":
          pushContent(`<span class="expr-ident">${escaped}</span>`);
          break;
        case "NUMBER":
          pushContent(`<span class="expr-number">${escaped}</span>`);
          break;
        case "SYMBOL":
          if (tok.value === "@") {
            pushContent(`<span class="expr-at">@</span>`);
          } else if (tok.value === ".") {
            pushContent(`<span class="expr-dot">.</span>`);
          } else if (tok.value === ",") {
            pushContent(`<wbr><span class="expr-symbol">,</span>`);
          } else {
            pushContent(`<span class="expr-symbol">${escaped}</span>`);
          }
          break;
        case "ARITH_OP":
          pushContent(`<span class="expr-arith-op">${escaped}</span>`);
          break;
        case "RANGE":
          pushContent(`<span class="expr-range">${escaped}</span>`);
          break;
        case "STRING":
          pushContent(`<span class="expr-string">"${escaped}"</span>`);
          break;
        default:
          pushContent(escaped);
      }
      i++;
    }
    return result.join("");
  }
  function renderPromptTitle(title) {
    const indexSuffix = renderIndexList(title.indices);
    return `<div class="prompt-title"><h1>${escapeHtml(title.name)}${indexSuffix}</h1></div>`;
  }
  function renderPathDesc(path2) {
    const segments = [];
    let current = path2;
    while (current) {
      const segIndexText = current.indices.length > 0 ? renderIndexList(current.indices) : "";
      segments.push(`${escapeHtml(current.base)}${segIndexText}`);
      current = current.next;
    }
    return segments.join(".");
  }
  function renderIndexContent(value) {
    switch (value.kind) {
      case "identifier":
        let result = escapeHtml(value.name);
        if (value.path) {
          result += "." + renderPathDesc(value.path);
        }
        const isNumber = /^\d+$/.test(value.name);
        const className = isNumber ? "index-number" : "index-identifier";
        return `<span class="${className}">${result}</span>`;
      case "context-var":
        return renderContextVarBlock(value);
      case "function":
        return renderFuncBlock(value);
      case "arithmetic":
        const left = renderIndexContent(value.left);
        const ops = value.operator.join("");
        const right = renderIndexContent(value.right);
        return `<span class="arithmetic-expr">${left}<span class="arith-op">${escapeHtml(ops)}</span>${right}</span>`;
      case "name-ref":
        return `<span class="name-ref">${escapeHtml(value.name)}</span>`;
    }
  }
  function renderIndexValue(index) {
    const content = renderIndexContent(index.value);
    return index.kind === "time-index" ? `<span class="time-index"><span class="at-symbol">@</span>${content}</span>` : `<span class="other-index">${content}</span>`;
  }
  function renderIndexList(indices) {
    if (indices.length === 0) return "";
    return `[${indices.map((idx) => renderIndexValue(idx)).join(",")}]`;
  }
  function renderPromptBody(body) {
    if (body.kind === "chat-prompt-body") {
      return body.body.map(renderPromptBodyItem).join("\n");
    } else {
      return renderNoneMessage(body.message);
    }
  }
  function renderNoneMessage(msg) {
    const bodyHtml = msg.body.map((b) => {
      return `<div class="role-body-block">${renderRoleBuildingBlock(b)}</div>`;
    }).join("\n");
    return `
<div class="none-message completion-prompt">
  <div class="none-message-header">Completion Prompt (no role)</div>
  ${bodyHtml}
</div>`;
  }
  function renderPromptBodyItem(item) {
    if (item.kind === "mark-block") {
      return renderMarkBlock(item);
    }
    return renderTopLevelBlock(item);
  }
  function renderTopLevelBlock(block) {
    switch (block.kind) {
      case "role-message":
        return renderRoleMessage(block);
      case "conditional-block-outside-role":
        return renderConditionalOutsideRole(block);
      case "loop-block-outside-role":
        return renderLoopOutsideRole(block);
      case "switch-block-outside-role":
        return renderSwitchOutsideRole(block);
      case "comment-block":
        return renderCommentBlock(block);
      case "mark-block":
        return renderMarkBlock(block);
      case "name-def":
        return renderNameDef(block);
      case "end-block":
        return renderEndBlock(block);
      case "roles-frag-invocation":
        return renderRolesFragInvocation(block);
      default:
        return "";
    }
  }
  function renderCommentBlock(block) {
    return `<div class="comment-block">// ${escapeHtml(block.text)}</div>`;
  }
  function renderNameDef(block) {
    const varName = escapeHtml(block.name);
    let valueHtml;
    if (block.value.kind === "context-var") {
      valueHtml = renderContextVarBlock(block.value);
    } else if (block.value.kind === "function") {
      valueHtml = renderFuncBlock(block.value);
    } else if (block.value.kind === "list-comprehension") {
      valueHtml = renderListComprehension(block.value);
    } else {
      valueHtml = renderStrFragInvocation(block.value);
    }
    return `<div class="name-def"><span class="keyword">Name</span> <span class="name-ref"><span class="segment">${varName}</span></span> <span class="name-assign">:=</span> ${valueHtml}</div>`;
  }
  function renderListComprehension(block) {
    let elementHtml;
    if (block.element.kind === "context-var") {
      elementHtml = renderContextVarBlock(block.element);
    } else if (block.element.kind === "function") {
      elementHtml = renderFuncBlock(block.element);
    } else {
      elementHtml = renderStrFragInvocation(block.element);
    }
    const iterableHtml = renderIterable(block.iterable);
    return `<span class="list-comp-wrapper"><span class="list-comprehension">[</span> ${elementHtml} <span class="list-comp-separator">|</span> <span class="list-comp-var">${escapeHtml(block.variable)}</span> <span class="list-comp-in">\u2208</span> ${iterableHtml} <span class="list-comprehension">]</span></span>`;
  }
  function renderNameRef(block) {
    const segments = [];
    const rootIndices = block.indices;
    const rootIndexText = rootIndices.length > 0 ? renderIndexList(block.indices) : "";
    segments.push(
      `<span class="segment">${escapeHtml(block.name)}${rootIndexText}</span>`
    );
    let current = block.path;
    while (current) {
      const segIndices = current.indices;
      const segIndexText = segIndices.length > 0 ? renderIndexList(current.indices) : "";
      segments.push(
        `<span class="segment">.${escapeHtml(current.base)}${segIndexText}</span>`
      );
      current = current.next;
    }
    const joined = segments.join("");
    return `<span class="name-ref">${joined}</span>`;
  }
  function renderMarkBlock(block) {
    const bodyHtml = block.body.map((b) => renderTopLevelBlock(b)).join("\n");
    const markNum = block.markNumber !== void 0 && !isNaN(block.markNumber) ? block.markNumber : 0;
    return `
<div class="mark-block">
  <div class="mark-block-content">
    ${bodyHtml}
  </div>
  <div class="mark-block-bracket">
    <span class="mark-bracket-line"></span>
    <span class="mark-bracket-number">${markNum}</span>
  </div>
</div>`;
  }
  function renderMarkBlockInsideRole(block) {
    const bodyHtml = block.body.map((b) => renderRoleBuildingBlock(b)).join("\n");
    const markNum = block.markNumber !== void 0 && !isNaN(block.markNumber) ? block.markNumber : 0;
    return `
<div class="mark-block">
  <div class="mark-block-content">
    ${bodyHtml}
  </div>
  <div class="mark-block-bracket">
    <span class="mark-bracket-line"></span>
    <span class="mark-bracket-number">${markNum}</span>
  </div>
</div>`;
  }
  function renderEndBlock(block) {
    const conditionHtml = renderExpressionTokens(block.condition);
    return `<div class="end-block"><span class="end-dashed-line"></span><span class="end-text"><span class="end-keyword">PromptEndsHere</span> <span class="keyword">when</span> <span class="condition-expr">${conditionHtml}</span></span></div>`;
  }
  function renderRoleMessage(msg) {
    const roleClass = escapeHtml(msg.role);
    const bodyHtml = msg.body.map((b) => {
      return `<div class="role-body-block">${renderRoleBuildingBlock(b)}</div>`;
    }).join("\n");
    return `
<div class="role-message ${roleClass}">
  <div class="role-message-header">Role: ${escapeHtml(msg.role)}</div>
  ${bodyHtml}
</div>`;
  }
  function renderRoleBuildingBlock(block) {
    switch (block.kind) {
      case "template":
        return renderTemplateBlock(block);
      case "context-var":
        return renderContextVarBlock(block);
      case "function":
        return renderFuncBlock(block);
      case "conditional-block-inside-role":
        return renderConditionalInsideRole(block);
      case "loop-block-inside-role":
        return renderLoopInsideRole(block);
      case "switch-block-inside-role":
        return renderSwitchInsideRole(block);
      case "mark-block-inside-role":
        return renderMarkBlockInsideRole(block);
      case "comment-block":
        return renderCommentBlock(block);
      case "name-def":
        return renderNameDef(block);
      case "name-ref":
        return renderNameRef(block);
      case "other-index":
        return renderIndexValue(block);
      case "end-block":
        return renderEndBlock(block);
      case "str-frag-invocation":
        return renderStrFragInvocation(block);
      default:
        return "";
    }
  }
  function renderFuncBlock(block) {
    if (block.name === "range" && block.arguments.length >= 2) {
      const startHtml = renderTextArgs(block.arguments[0]);
      const endHtml = renderTextArgs(block.arguments[1]);
      const stepHtml = block.arguments.length >= 3 ? `<span class="range-step"><span class="range-keyword">every</span><span class="range-step-value">${renderTextArgs(block.arguments[2])}</span></span>` : "";
      const rangeCore = `<span class="range-expr"><span class="range-start">${startHtml}</span><span class="range-dots">...</span><span class="range-end">${endHtml}</span>${stepHtml}</span>`;
      if (block.comment) {
        return `<span class="block-with-comment">${rangeCore}<span class="inline-comment"> // ${escapeHtml(block.comment)}</span></span>`;
      }
      return rangeCore;
    }
    const argsText = block.arguments.map(renderTextArgs).join(", ");
    const resultIndices = block.indices && block.indices.length > 0 ? renderIndexList(block.indices) : "";
    const isBuiltinMath = block.name === "min" || block.name === "max";
    const funcCore = isBuiltinMath ? `<span class="builtin-func">${escapeHtml(block.name)}(${argsText})${resultIndices}</span>` : `<span class="func-block"><span class="func-name">${escapeHtml(block.name)}</span><span class="func-args-wrapper">(${argsText})${resultIndices}</span></span>`;
    if (block.comment) {
      return `<span class="block-with-comment">${funcCore}<span class="inline-comment"> // ${escapeHtml(block.comment)}</span></span>`;
    }
    return funcCore;
  }
  function renderTextArgs(arg) {
    switch (arg.kind) {
      case "context-var":
        return renderContextVarBlock(arg);
      case "function":
        return renderFuncBlock(arg);
      case "time-index":
      case "other-index":
        return renderIndexValue(arg);
      case "identifier":
        let result = escapeHtml(arg.name);
        if (arg.path) {
          result += "." + renderPathDesc(arg.path);
        }
        return `<span class="identifier">${result}</span>`;
      case "arithmetic":
        const left = renderTextArgs(arg.left);
        const ops = arg.operator.join("");
        const right = renderTextArgs(arg.right);
        return `<span class="arithmetic-expr">${left}${escapeHtml(ops)}${right}</span>`;
      case "name-ref":
        return renderNameRef(arg);
      case "str-frag-invocation":
        return renderStrFragInvocation(arg);
    }
  }
  function renderTemplateBlock(block) {
    const argsText = block.arguments.length > 0 ? `(${block.arguments.map(renderTextArgs).join(", ")})` : "";
    const core = `<span class="template-block"><span class="template-name-and-args">${escapeHtml(
      block.name
    )}${argsText}</span></span>`;
    if (block.comment) {
      return `<span class="block-with-comment">${core}<span class="comment"> // ${escapeHtml(block.comment)}</span></span>`;
    }
    return core;
  }
  function renderContextVarBlock(block) {
    const segments = [];
    const rootIndices = block.indices;
    const rootIndexText = rootIndices.length > 0 ? renderIndexList(block.indices) : "";
    segments.push(
      `<span class="segment base">${escapeHtml(block.base)}${rootIndexText}</span>`
    );
    let current = block.path;
    while (current) {
      const segIndices = current.indices;
      const segIndexText = segIndices.length > 0 ? renderIndexList(current.indices) : "";
      segments.push(
        `<span class="segment">.${escapeHtml(current.base)}${segIndexText}</span>`
      );
      current = current.next;
    }
    const joined = segments.join("");
    const namespaceClass = `context-var-${block.base.toLowerCase()}`;
    if (block.comment) {
      return `<span class="block-with-comment"><span class="context-var ${namespaceClass}">${joined}</span><span class="inline-comment"> // ${escapeHtml(block.comment)}</span></span>`;
    }
    return `<span class="context-var ${namespaceClass}">${joined}</span>`;
  }
  function renderIterable(iterable) {
    if (iterable.kind === "range-expr") {
      return renderRangeExpr(iterable);
    } else {
      return renderExpressionTokens(iterable.tokens);
    }
  }
  function renderRangeExpr(range) {
    const startHtml = renderExpressionTokens(range.start);
    const endHtml = renderExpressionTokens(range.end);
    const stepHtml = range.step ? `<span class="range-step"><span class="range-keyword">every</span><span class="range-step-value">${renderExpressionTokens(range.step)}</span></span>` : "";
    return `<span class="range-expr"><span class="range-start">${startHtml}</span><span class="range-dots">...</span><span class="range-end">${endHtml}</span>${stepHtml}</span>`;
  }
  function renderLoopOutsideRole(block) {
    const indexHtml = `<span class="loop-var">${renderIndexContent(block.index.value)}</span>`;
    const iterableHtml = `<span class="loop-iterable">${renderIterable(block.iterable)}</span>`;
    const header = `<span class="keyword">ForEach</span> ${indexHtml}: ${iterableHtml}`;
    const bodyHtml = block.body.map(
      (child) => `<div class="loop-child">${renderTopLevelBlock(child)}</div>`
    ).join("\n");
    return wrapBlock(
      "loop-block-outside-role",
      header,
      bodyHtml
    );
  }
  function renderLoopInsideRole(block) {
    const indexHtml = `<span class="loop-var">${renderIndexContent(block.index.value)}</span>`;
    const iterableHtml = `<span class="loop-iterable">${renderIterable(block.iterable)}</span>`;
    const header = `<span class="keyword">ForEach</span> ${indexHtml}: ${iterableHtml}`;
    const bodyHtml = block.body.map(
      (child) => `<div class="role-loop-child">${renderRoleBuildingBlock(child)}</div>`
    ).join("\n");
    return wrapBlock("loop-block-inside-role", header, bodyHtml);
  }
  function renderSwitchOutsideRole(block) {
    const exprHtml = `<span class="switch-expr">${renderExpressionTokens(block.expression)}</span>`;
    const header = `<span class="keyword">Switch</span>(${exprHtml}):`;
    const casesHtml = block.cases.map((c) => {
      const bodyHtml = c.body.map(
        (child) => `<div class="switch-child">${renderTopLevelBlock(child)}</div>`
      ).join("\n");
      return wrapBlock(
        "switch-case",
        `<span class="keyword">Case</span> <span class="case-match">${renderExpressionTokens(c.match)}</span>:`,
        bodyHtml
      );
    }).join("\n");
    const defaultHtml = block.defaultCase ? (() => {
      const bodyHtml = block.defaultCase.body.map(
        (child) => `<div class="switch-child">${renderTopLevelBlock(child)}</div>`
      ).join("\n");
      return wrapBlock(
        "switch-default",
        `<span class="keyword">Default</span>:`,
        bodyHtml
      );
    })() : "";
    return wrapBlock(
      "switch-block-outside-role",
      header,
      `${casesHtml}${defaultHtml}`
    );
  }
  function renderSwitchInsideRole(block) {
    const exprHtml = `<span class="switch-expr">${renderExpressionTokens(block.expression)}</span>`;
    const header = `<span class="keyword">Switch</span>(${exprHtml}):`;
    const casesHtml = block.cases.map((c) => {
      const bodyHtml = c.body.map(
        (child) => `<div class="role-switch-child">${renderRoleBuildingBlock(child)}</div>`
      ).join("\n");
      return wrapBlock(
        "switch-case",
        `<span class="keyword">Case</span> <span class="case-match">${renderExpressionTokens(c.match)}</span>:`,
        bodyHtml
      );
    }).join("\n");
    const defaultHtml = block.defaultCase ? (() => {
      const bodyHtml = block.defaultCase.body.map(
        (child) => `<div class="role-switch-child">${renderRoleBuildingBlock(child)}</div>`
      ).join("\n");
      return wrapBlock(
        "switch-default",
        `<span class="keyword">Default</span>:`,
        bodyHtml
      );
    })() : "";
    return wrapBlock(
      "switch-block-inside-role",
      header,
      `${casesHtml}${defaultHtml}`
    );
  }
  function renderConditionalInsideRole(block) {
    const renderBody = (body) => body.map(
      (child) => `<div class="role-condition-child">${renderRoleBuildingBlock(child)}</div>`
    ).join("\n");
    const ifHeader = `<span class="keyword">If</span> <span class="condition-expr">${renderExpressionTokens(block.Ifcondition)}</span>:`;
    let result = wrapBlock("conditional-block-inside-role", ifHeader, renderBody(block.IfBody));
    for (let i = 0; i < block.elseif.length; i++) {
      const elseifHeader = `<span class="keyword">ElseIf</span> <span class="condition-expr">${renderExpressionTokens(block.elseif[i])}</span>:`;
      result += wrapBlock("conditional-block-inside-role", elseifHeader, renderBody(block.elseifBody[i]));
    }
    if (block.elseBody && block.elseBody.length > 0) {
      const elseHeader = `<span class="keyword">Else</span>:`;
      result += wrapBlock("conditional-block-inside-role", elseHeader, renderBody(block.elseBody));
    }
    return result;
  }
  function renderConditionalOutsideRole(block) {
    const renderBody = (body) => body.map(
      (child) => `<div class="conditional-child">${renderTopLevelBlock(child)}</div>`
    ).join("\n");
    const ifHeader = `<span class="keyword">If</span> <span class="condition-expr">${renderExpressionTokens(block.Ifcondition)}</span>:`;
    let result = wrapBlock("conditional-block-outside-role", ifHeader, renderBody(block.IfBody));
    for (let i = 0; i < block.elseif.length; i++) {
      const elseifHeader = `<span class="keyword">ElseIf</span> <span class="condition-expr">${renderExpressionTokens(block.elseif[i])}</span>:`;
      result += wrapBlock("conditional-block-outside-role", elseifHeader, renderBody(block.elseifBody[i]));
    }
    if (block.elseBody && block.elseBody.length > 0) {
      const elseHeader = `<span class="keyword">Else</span>:`;
      result += wrapBlock("conditional-block-outside-role", elseHeader, renderBody(block.elseBody));
    }
    return result;
  }
  function renderStrFragDef(frag, style = "default") {
    const paramsHtml = frag.params.length > 0 ? `[${frag.params.map(renderTextArgs).join(", ")}]` : "";
    const titleHtml = `<div class="frag-def-title"><h1>${escapeHtml(frag.name)}${paramsHtml}</h1><span class="frag-badge">SF</span></div>`;
    const bodyHtml = frag.body.map((b) => {
      return `<div class="role-body-block">${renderRoleBuildingBlock(b)}</div>`;
    }).join("\n");
    return `<div class="frag-def-container frag-style-${style}">${titleHtml}<div class="frag-body">${bodyHtml}</div></div>`;
  }
  function renderRolesFragDef(frag, style = "default") {
    const paramsHtml = frag.params.length > 0 ? `[${frag.params.map(renderTextArgs).join(", ")}]` : "";
    const titleHtml = `<div class="frag-def-title"><h1>${escapeHtml(frag.name)}${paramsHtml}</h1><span class="frag-badge">RF</span></div>`;
    const bodyHtml = frag.body.map(renderPromptBodyItem).join("\n");
    return `<div class="frag-def-container frag-style-${style}">${titleHtml}<div class="frag-body">${bodyHtml}</div></div>`;
  }
  function renderStrFragInvocation(block) {
    const argsText = block.arguments.length > 0 ? `[${block.arguments.map(renderTextArgs).join(", ")}]` : "";
    return `<span class="frag-invocation-wrapper"><span class="frag-keyword">Frag</span> <span class="frag-invocation"><span class="frag-name">${escapeHtml(block.name)}</span><span class="frag-args-wrapper">${argsText}</span></span></span>`;
  }
  function renderRolesFragInvocation(block) {
    const argsText = block.arguments.length > 0 ? `[${block.arguments.map(renderTextArgs).join(", ")}]` : "";
    return `<span class="frag-invocation-wrapper"><span class="frag-keyword">Frag</span> <span class="frag-invocation"><span class="frag-name">${escapeHtml(block.name)}</span><span class="frag-args-wrapper">${argsText}</span></span></span>`;
  }

  // node_modules/opentype.js/dist/opentype.module.js
  if (!String.prototype.codePointAt) {
    (function() {
      var defineProperty = function() {
        try {
          var object = {};
          var $defineProperty = Object.defineProperty;
          var result = $defineProperty(object, object, object) && $defineProperty;
        } catch (error) {
        }
        return result;
      }();
      var codePointAt = function(position) {
        if (this == null) {
          throw TypeError();
        }
        var string = String(this);
        var size = string.length;
        var index = position ? Number(position) : 0;
        if (index != index) {
          index = 0;
        }
        if (index < 0 || index >= size) {
          return void 0;
        }
        var first = string.charCodeAt(index);
        var second;
        if (
          // check if it’s the start of a surrogate pair
          first >= 55296 && first <= 56319 && // high surrogate
          size > index + 1
        ) {
          second = string.charCodeAt(index + 1);
          if (second >= 56320 && second <= 57343) {
            return (first - 55296) * 1024 + second - 56320 + 65536;
          }
        }
        return first;
      };
      if (defineProperty) {
        defineProperty(String.prototype, "codePointAt", {
          "value": codePointAt,
          "configurable": true,
          "writable": true
        });
      } else {
        String.prototype.codePointAt = codePointAt;
      }
    })();
  }
  var TINF_OK = 0;
  var TINF_DATA_ERROR = -3;
  function Tree() {
    this.table = new Uint16Array(16);
    this.trans = new Uint16Array(288);
  }
  function Data(source, dest) {
    this.source = source;
    this.sourceIndex = 0;
    this.tag = 0;
    this.bitcount = 0;
    this.dest = dest;
    this.destLen = 0;
    this.ltree = new Tree();
    this.dtree = new Tree();
  }
  var sltree = new Tree();
  var sdtree = new Tree();
  var length_bits = new Uint8Array(30);
  var length_base = new Uint16Array(30);
  var dist_bits = new Uint8Array(30);
  var dist_base = new Uint16Array(30);
  var clcidx = new Uint8Array([
    16,
    17,
    18,
    0,
    8,
    7,
    9,
    6,
    10,
    5,
    11,
    4,
    12,
    3,
    13,
    2,
    14,
    1,
    15
  ]);
  var code_tree = new Tree();
  var lengths = new Uint8Array(288 + 32);
  function tinf_build_bits_base(bits, base, delta, first) {
    var i, sum;
    for (i = 0; i < delta; ++i) {
      bits[i] = 0;
    }
    for (i = 0; i < 30 - delta; ++i) {
      bits[i + delta] = i / delta | 0;
    }
    for (sum = first, i = 0; i < 30; ++i) {
      base[i] = sum;
      sum += 1 << bits[i];
    }
  }
  function tinf_build_fixed_trees(lt, dt) {
    var i;
    for (i = 0; i < 7; ++i) {
      lt.table[i] = 0;
    }
    lt.table[7] = 24;
    lt.table[8] = 152;
    lt.table[9] = 112;
    for (i = 0; i < 24; ++i) {
      lt.trans[i] = 256 + i;
    }
    for (i = 0; i < 144; ++i) {
      lt.trans[24 + i] = i;
    }
    for (i = 0; i < 8; ++i) {
      lt.trans[24 + 144 + i] = 280 + i;
    }
    for (i = 0; i < 112; ++i) {
      lt.trans[24 + 144 + 8 + i] = 144 + i;
    }
    for (i = 0; i < 5; ++i) {
      dt.table[i] = 0;
    }
    dt.table[5] = 32;
    for (i = 0; i < 32; ++i) {
      dt.trans[i] = i;
    }
  }
  var offs = new Uint16Array(16);
  function tinf_build_tree(t, lengths2, off, num) {
    var i, sum;
    for (i = 0; i < 16; ++i) {
      t.table[i] = 0;
    }
    for (i = 0; i < num; ++i) {
      t.table[lengths2[off + i]]++;
    }
    t.table[0] = 0;
    for (sum = 0, i = 0; i < 16; ++i) {
      offs[i] = sum;
      sum += t.table[i];
    }
    for (i = 0; i < num; ++i) {
      if (lengths2[off + i]) {
        t.trans[offs[lengths2[off + i]]++] = i;
      }
    }
  }
  function tinf_getbit(d) {
    if (!d.bitcount--) {
      d.tag = d.source[d.sourceIndex++];
      d.bitcount = 7;
    }
    var bit = d.tag & 1;
    d.tag >>>= 1;
    return bit;
  }
  function tinf_read_bits(d, num, base) {
    if (!num) {
      return base;
    }
    while (d.bitcount < 24) {
      d.tag |= d.source[d.sourceIndex++] << d.bitcount;
      d.bitcount += 8;
    }
    var val = d.tag & 65535 >>> 16 - num;
    d.tag >>>= num;
    d.bitcount -= num;
    return val + base;
  }
  function tinf_decode_symbol(d, t) {
    while (d.bitcount < 24) {
      d.tag |= d.source[d.sourceIndex++] << d.bitcount;
      d.bitcount += 8;
    }
    var sum = 0, cur = 0, len = 0;
    var tag = d.tag;
    do {
      cur = 2 * cur + (tag & 1);
      tag >>>= 1;
      ++len;
      sum += t.table[len];
      cur -= t.table[len];
    } while (cur >= 0);
    d.tag = tag;
    d.bitcount -= len;
    return t.trans[sum + cur];
  }
  function tinf_decode_trees(d, lt, dt) {
    var hlit, hdist, hclen;
    var i, num, length;
    hlit = tinf_read_bits(d, 5, 257);
    hdist = tinf_read_bits(d, 5, 1);
    hclen = tinf_read_bits(d, 4, 4);
    for (i = 0; i < 19; ++i) {
      lengths[i] = 0;
    }
    for (i = 0; i < hclen; ++i) {
      var clen = tinf_read_bits(d, 3, 0);
      lengths[clcidx[i]] = clen;
    }
    tinf_build_tree(code_tree, lengths, 0, 19);
    for (num = 0; num < hlit + hdist; ) {
      var sym = tinf_decode_symbol(d, code_tree);
      switch (sym) {
        case 16:
          var prev = lengths[num - 1];
          for (length = tinf_read_bits(d, 2, 3); length; --length) {
            lengths[num++] = prev;
          }
          break;
        case 17:
          for (length = tinf_read_bits(d, 3, 3); length; --length) {
            lengths[num++] = 0;
          }
          break;
        case 18:
          for (length = tinf_read_bits(d, 7, 11); length; --length) {
            lengths[num++] = 0;
          }
          break;
        default:
          lengths[num++] = sym;
          break;
      }
    }
    tinf_build_tree(lt, lengths, 0, hlit);
    tinf_build_tree(dt, lengths, hlit, hdist);
  }
  function tinf_inflate_block_data(d, lt, dt) {
    while (1) {
      var sym = tinf_decode_symbol(d, lt);
      if (sym === 256) {
        return TINF_OK;
      }
      if (sym < 256) {
        d.dest[d.destLen++] = sym;
      } else {
        var length, dist, offs2;
        var i;
        sym -= 257;
        length = tinf_read_bits(d, length_bits[sym], length_base[sym]);
        dist = tinf_decode_symbol(d, dt);
        offs2 = d.destLen - tinf_read_bits(d, dist_bits[dist], dist_base[dist]);
        for (i = offs2; i < offs2 + length; ++i) {
          d.dest[d.destLen++] = d.dest[i];
        }
      }
    }
  }
  function tinf_inflate_uncompressed_block(d) {
    var length, invlength;
    var i;
    while (d.bitcount > 8) {
      d.sourceIndex--;
      d.bitcount -= 8;
    }
    length = d.source[d.sourceIndex + 1];
    length = 256 * length + d.source[d.sourceIndex];
    invlength = d.source[d.sourceIndex + 3];
    invlength = 256 * invlength + d.source[d.sourceIndex + 2];
    if (length !== (~invlength & 65535)) {
      return TINF_DATA_ERROR;
    }
    d.sourceIndex += 4;
    for (i = length; i; --i) {
      d.dest[d.destLen++] = d.source[d.sourceIndex++];
    }
    d.bitcount = 0;
    return TINF_OK;
  }
  function tinf_uncompress(source, dest) {
    var d = new Data(source, dest);
    var bfinal, btype, res;
    do {
      bfinal = tinf_getbit(d);
      btype = tinf_read_bits(d, 2, 0);
      switch (btype) {
        case 0:
          res = tinf_inflate_uncompressed_block(d);
          break;
        case 1:
          res = tinf_inflate_block_data(d, sltree, sdtree);
          break;
        case 2:
          tinf_decode_trees(d, d.ltree, d.dtree);
          res = tinf_inflate_block_data(d, d.ltree, d.dtree);
          break;
        default:
          res = TINF_DATA_ERROR;
      }
      if (res !== TINF_OK) {
        throw new Error("Data error");
      }
    } while (!bfinal);
    if (d.destLen < d.dest.length) {
      if (typeof d.dest.slice === "function") {
        return d.dest.slice(0, d.destLen);
      } else {
        return d.dest.subarray(0, d.destLen);
      }
    }
    return d.dest;
  }
  tinf_build_fixed_trees(sltree, sdtree);
  tinf_build_bits_base(length_bits, length_base, 4, 3);
  tinf_build_bits_base(dist_bits, dist_base, 2, 1);
  length_bits[28] = 0;
  length_base[28] = 258;
  var tinyInflate = tinf_uncompress;
  function derive(v0, v1, v2, v3, t) {
    return Math.pow(1 - t, 3) * v0 + 3 * Math.pow(1 - t, 2) * t * v1 + 3 * (1 - t) * Math.pow(t, 2) * v2 + Math.pow(t, 3) * v3;
  }
  function BoundingBox() {
    this.x1 = Number.NaN;
    this.y1 = Number.NaN;
    this.x2 = Number.NaN;
    this.y2 = Number.NaN;
  }
  BoundingBox.prototype.isEmpty = function() {
    return isNaN(this.x1) || isNaN(this.y1) || isNaN(this.x2) || isNaN(this.y2);
  };
  BoundingBox.prototype.addPoint = function(x, y) {
    if (typeof x === "number") {
      if (isNaN(this.x1) || isNaN(this.x2)) {
        this.x1 = x;
        this.x2 = x;
      }
      if (x < this.x1) {
        this.x1 = x;
      }
      if (x > this.x2) {
        this.x2 = x;
      }
    }
    if (typeof y === "number") {
      if (isNaN(this.y1) || isNaN(this.y2)) {
        this.y1 = y;
        this.y2 = y;
      }
      if (y < this.y1) {
        this.y1 = y;
      }
      if (y > this.y2) {
        this.y2 = y;
      }
    }
  };
  BoundingBox.prototype.addX = function(x) {
    this.addPoint(x, null);
  };
  BoundingBox.prototype.addY = function(y) {
    this.addPoint(null, y);
  };
  BoundingBox.prototype.addBezier = function(x0, y0, x1, y1, x2, y2, x, y) {
    var p0 = [x0, y0];
    var p1 = [x1, y1];
    var p2 = [x2, y2];
    var p3 = [x, y];
    this.addPoint(x0, y0);
    this.addPoint(x, y);
    for (var i = 0; i <= 1; i++) {
      var b = 6 * p0[i] - 12 * p1[i] + 6 * p2[i];
      var a = -3 * p0[i] + 9 * p1[i] - 9 * p2[i] + 3 * p3[i];
      var c = 3 * p1[i] - 3 * p0[i];
      if (a === 0) {
        if (b === 0) {
          continue;
        }
        var t = -c / b;
        if (0 < t && t < 1) {
          if (i === 0) {
            this.addX(derive(p0[i], p1[i], p2[i], p3[i], t));
          }
          if (i === 1) {
            this.addY(derive(p0[i], p1[i], p2[i], p3[i], t));
          }
        }
        continue;
      }
      var b2ac = Math.pow(b, 2) - 4 * c * a;
      if (b2ac < 0) {
        continue;
      }
      var t1 = (-b + Math.sqrt(b2ac)) / (2 * a);
      if (0 < t1 && t1 < 1) {
        if (i === 0) {
          this.addX(derive(p0[i], p1[i], p2[i], p3[i], t1));
        }
        if (i === 1) {
          this.addY(derive(p0[i], p1[i], p2[i], p3[i], t1));
        }
      }
      var t2 = (-b - Math.sqrt(b2ac)) / (2 * a);
      if (0 < t2 && t2 < 1) {
        if (i === 0) {
          this.addX(derive(p0[i], p1[i], p2[i], p3[i], t2));
        }
        if (i === 1) {
          this.addY(derive(p0[i], p1[i], p2[i], p3[i], t2));
        }
      }
    }
  };
  BoundingBox.prototype.addQuad = function(x0, y0, x1, y1, x, y) {
    var cp1x = x0 + 2 / 3 * (x1 - x0);
    var cp1y = y0 + 2 / 3 * (y1 - y0);
    var cp2x = cp1x + 1 / 3 * (x - x0);
    var cp2y = cp1y + 1 / 3 * (y - y0);
    this.addBezier(x0, y0, cp1x, cp1y, cp2x, cp2y, x, y);
  };
  function Path() {
    this.commands = [];
    this.fill = "black";
    this.stroke = null;
    this.strokeWidth = 1;
  }
  Path.prototype.moveTo = function(x, y) {
    this.commands.push({
      type: "M",
      x,
      y
    });
  };
  Path.prototype.lineTo = function(x, y) {
    this.commands.push({
      type: "L",
      x,
      y
    });
  };
  Path.prototype.curveTo = Path.prototype.bezierCurveTo = function(x1, y1, x2, y2, x, y) {
    this.commands.push({
      type: "C",
      x1,
      y1,
      x2,
      y2,
      x,
      y
    });
  };
  Path.prototype.quadTo = Path.prototype.quadraticCurveTo = function(x1, y1, x, y) {
    this.commands.push({
      type: "Q",
      x1,
      y1,
      x,
      y
    });
  };
  Path.prototype.close = Path.prototype.closePath = function() {
    this.commands.push({
      type: "Z"
    });
  };
  Path.prototype.extend = function(pathOrCommands) {
    if (pathOrCommands.commands) {
      pathOrCommands = pathOrCommands.commands;
    } else if (pathOrCommands instanceof BoundingBox) {
      var box = pathOrCommands;
      this.moveTo(box.x1, box.y1);
      this.lineTo(box.x2, box.y1);
      this.lineTo(box.x2, box.y2);
      this.lineTo(box.x1, box.y2);
      this.close();
      return;
    }
    Array.prototype.push.apply(this.commands, pathOrCommands);
  };
  Path.prototype.getBoundingBox = function() {
    var box = new BoundingBox();
    var startX = 0;
    var startY = 0;
    var prevX = 0;
    var prevY = 0;
    for (var i = 0; i < this.commands.length; i++) {
      var cmd = this.commands[i];
      switch (cmd.type) {
        case "M":
          box.addPoint(cmd.x, cmd.y);
          startX = prevX = cmd.x;
          startY = prevY = cmd.y;
          break;
        case "L":
          box.addPoint(cmd.x, cmd.y);
          prevX = cmd.x;
          prevY = cmd.y;
          break;
        case "Q":
          box.addQuad(prevX, prevY, cmd.x1, cmd.y1, cmd.x, cmd.y);
          prevX = cmd.x;
          prevY = cmd.y;
          break;
        case "C":
          box.addBezier(prevX, prevY, cmd.x1, cmd.y1, cmd.x2, cmd.y2, cmd.x, cmd.y);
          prevX = cmd.x;
          prevY = cmd.y;
          break;
        case "Z":
          prevX = startX;
          prevY = startY;
          break;
        default:
          throw new Error("Unexpected path command " + cmd.type);
      }
    }
    if (box.isEmpty()) {
      box.addPoint(0, 0);
    }
    return box;
  };
  Path.prototype.draw = function(ctx) {
    ctx.beginPath();
    for (var i = 0; i < this.commands.length; i += 1) {
      var cmd = this.commands[i];
      if (cmd.type === "M") {
        ctx.moveTo(cmd.x, cmd.y);
      } else if (cmd.type === "L") {
        ctx.lineTo(cmd.x, cmd.y);
      } else if (cmd.type === "C") {
        ctx.bezierCurveTo(cmd.x1, cmd.y1, cmd.x2, cmd.y2, cmd.x, cmd.y);
      } else if (cmd.type === "Q") {
        ctx.quadraticCurveTo(cmd.x1, cmd.y1, cmd.x, cmd.y);
      } else if (cmd.type === "Z") {
        ctx.closePath();
      }
    }
    if (this.fill) {
      ctx.fillStyle = this.fill;
      ctx.fill();
    }
    if (this.stroke) {
      ctx.strokeStyle = this.stroke;
      ctx.lineWidth = this.strokeWidth;
      ctx.stroke();
    }
  };
  Path.prototype.toPathData = function(decimalPlaces) {
    decimalPlaces = decimalPlaces !== void 0 ? decimalPlaces : 2;
    function floatToString(v) {
      if (Math.round(v) === v) {
        return "" + Math.round(v);
      } else {
        return v.toFixed(decimalPlaces);
      }
    }
    function packValues() {
      var arguments$1 = arguments;
      var s = "";
      for (var i2 = 0; i2 < arguments.length; i2 += 1) {
        var v = arguments$1[i2];
        if (v >= 0 && i2 > 0) {
          s += " ";
        }
        s += floatToString(v);
      }
      return s;
    }
    var d = "";
    for (var i = 0; i < this.commands.length; i += 1) {
      var cmd = this.commands[i];
      if (cmd.type === "M") {
        d += "M" + packValues(cmd.x, cmd.y);
      } else if (cmd.type === "L") {
        d += "L" + packValues(cmd.x, cmd.y);
      } else if (cmd.type === "C") {
        d += "C" + packValues(cmd.x1, cmd.y1, cmd.x2, cmd.y2, cmd.x, cmd.y);
      } else if (cmd.type === "Q") {
        d += "Q" + packValues(cmd.x1, cmd.y1, cmd.x, cmd.y);
      } else if (cmd.type === "Z") {
        d += "Z";
      }
    }
    return d;
  };
  Path.prototype.toSVG = function(decimalPlaces) {
    var svg = '<path d="';
    svg += this.toPathData(decimalPlaces);
    svg += '"';
    if (this.fill && this.fill !== "black") {
      if (this.fill === null) {
        svg += ' fill="none"';
      } else {
        svg += ' fill="' + this.fill + '"';
      }
    }
    if (this.stroke) {
      svg += ' stroke="' + this.stroke + '" stroke-width="' + this.strokeWidth + '"';
    }
    svg += "/>";
    return svg;
  };
  Path.prototype.toDOMElement = function(decimalPlaces) {
    var temporaryPath = this.toPathData(decimalPlaces);
    var newPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    newPath.setAttribute("d", temporaryPath);
    return newPath;
  };
  function fail(message) {
    throw new Error(message);
  }
  function argument(predicate, message) {
    if (!predicate) {
      fail(message);
    }
  }
  var check = { fail, argument, assert: argument };
  var LIMIT16 = 32768;
  var LIMIT32 = 2147483648;
  var decode = {};
  var encode = {};
  var sizeOf = {};
  function constant(v) {
    return function() {
      return v;
    };
  }
  encode.BYTE = function(v) {
    check.argument(v >= 0 && v <= 255, "Byte value should be between 0 and 255.");
    return [v];
  };
  sizeOf.BYTE = constant(1);
  encode.CHAR = function(v) {
    return [v.charCodeAt(0)];
  };
  sizeOf.CHAR = constant(1);
  encode.CHARARRAY = function(v) {
    if (typeof v === "undefined") {
      v = "";
      console.warn("Undefined CHARARRAY encountered and treated as an empty string. This is probably caused by a missing glyph name.");
    }
    var b = [];
    for (var i = 0; i < v.length; i += 1) {
      b[i] = v.charCodeAt(i);
    }
    return b;
  };
  sizeOf.CHARARRAY = function(v) {
    if (typeof v === "undefined") {
      return 0;
    }
    return v.length;
  };
  encode.USHORT = function(v) {
    return [v >> 8 & 255, v & 255];
  };
  sizeOf.USHORT = constant(2);
  encode.SHORT = function(v) {
    if (v >= LIMIT16) {
      v = -(2 * LIMIT16 - v);
    }
    return [v >> 8 & 255, v & 255];
  };
  sizeOf.SHORT = constant(2);
  encode.UINT24 = function(v) {
    return [v >> 16 & 255, v >> 8 & 255, v & 255];
  };
  sizeOf.UINT24 = constant(3);
  encode.ULONG = function(v) {
    return [v >> 24 & 255, v >> 16 & 255, v >> 8 & 255, v & 255];
  };
  sizeOf.ULONG = constant(4);
  encode.LONG = function(v) {
    if (v >= LIMIT32) {
      v = -(2 * LIMIT32 - v);
    }
    return [v >> 24 & 255, v >> 16 & 255, v >> 8 & 255, v & 255];
  };
  sizeOf.LONG = constant(4);
  encode.FIXED = encode.ULONG;
  sizeOf.FIXED = sizeOf.ULONG;
  encode.FWORD = encode.SHORT;
  sizeOf.FWORD = sizeOf.SHORT;
  encode.UFWORD = encode.USHORT;
  sizeOf.UFWORD = sizeOf.USHORT;
  encode.LONGDATETIME = function(v) {
    return [0, 0, 0, 0, v >> 24 & 255, v >> 16 & 255, v >> 8 & 255, v & 255];
  };
  sizeOf.LONGDATETIME = constant(8);
  encode.TAG = function(v) {
    check.argument(v.length === 4, "Tag should be exactly 4 ASCII characters.");
    return [
      v.charCodeAt(0),
      v.charCodeAt(1),
      v.charCodeAt(2),
      v.charCodeAt(3)
    ];
  };
  sizeOf.TAG = constant(4);
  encode.Card8 = encode.BYTE;
  sizeOf.Card8 = sizeOf.BYTE;
  encode.Card16 = encode.USHORT;
  sizeOf.Card16 = sizeOf.USHORT;
  encode.OffSize = encode.BYTE;
  sizeOf.OffSize = sizeOf.BYTE;
  encode.SID = encode.USHORT;
  sizeOf.SID = sizeOf.USHORT;
  encode.NUMBER = function(v) {
    if (v >= -107 && v <= 107) {
      return [v + 139];
    } else if (v >= 108 && v <= 1131) {
      v = v - 108;
      return [(v >> 8) + 247, v & 255];
    } else if (v >= -1131 && v <= -108) {
      v = -v - 108;
      return [(v >> 8) + 251, v & 255];
    } else if (v >= -32768 && v <= 32767) {
      return encode.NUMBER16(v);
    } else {
      return encode.NUMBER32(v);
    }
  };
  sizeOf.NUMBER = function(v) {
    return encode.NUMBER(v).length;
  };
  encode.NUMBER16 = function(v) {
    return [28, v >> 8 & 255, v & 255];
  };
  sizeOf.NUMBER16 = constant(3);
  encode.NUMBER32 = function(v) {
    return [29, v >> 24 & 255, v >> 16 & 255, v >> 8 & 255, v & 255];
  };
  sizeOf.NUMBER32 = constant(5);
  encode.REAL = function(v) {
    var value = v.toString();
    var m = /\.(\d*?)(?:9{5,20}|0{5,20})\d{0,2}(?:e(.+)|$)/.exec(value);
    if (m) {
      var epsilon = parseFloat("1e" + ((m[2] ? +m[2] : 0) + m[1].length));
      value = (Math.round(v * epsilon) / epsilon).toString();
    }
    var nibbles = "";
    for (var i = 0, ii = value.length; i < ii; i += 1) {
      var c = value[i];
      if (c === "e") {
        nibbles += value[++i] === "-" ? "c" : "b";
      } else if (c === ".") {
        nibbles += "a";
      } else if (c === "-") {
        nibbles += "e";
      } else {
        nibbles += c;
      }
    }
    nibbles += nibbles.length & 1 ? "f" : "ff";
    var out = [30];
    for (var i$1 = 0, ii$1 = nibbles.length; i$1 < ii$1; i$1 += 2) {
      out.push(parseInt(nibbles.substr(i$1, 2), 16));
    }
    return out;
  };
  sizeOf.REAL = function(v) {
    return encode.REAL(v).length;
  };
  encode.NAME = encode.CHARARRAY;
  sizeOf.NAME = sizeOf.CHARARRAY;
  encode.STRING = encode.CHARARRAY;
  sizeOf.STRING = sizeOf.CHARARRAY;
  decode.UTF8 = function(data, offset, numBytes) {
    var codePoints = [];
    var numChars = numBytes;
    for (var j = 0; j < numChars; j++, offset += 1) {
      codePoints[j] = data.getUint8(offset);
    }
    return String.fromCharCode.apply(null, codePoints);
  };
  decode.UTF16 = function(data, offset, numBytes) {
    var codePoints = [];
    var numChars = numBytes / 2;
    for (var j = 0; j < numChars; j++, offset += 2) {
      codePoints[j] = data.getUint16(offset);
    }
    return String.fromCharCode.apply(null, codePoints);
  };
  encode.UTF16 = function(v) {
    var b = [];
    for (var i = 0; i < v.length; i += 1) {
      var codepoint = v.charCodeAt(i);
      b[b.length] = codepoint >> 8 & 255;
      b[b.length] = codepoint & 255;
    }
    return b;
  };
  sizeOf.UTF16 = function(v) {
    return v.length * 2;
  };
  var eightBitMacEncodings = {
    "x-mac-croatian": (
      // Python: 'mac_croatian'
      "\xC4\xC5\xC7\xC9\xD1\xD6\xDC\xE1\xE0\xE2\xE4\xE3\xE5\xE7\xE9\xE8\xEA\xEB\xED\xEC\xEE\xEF\xF1\xF3\xF2\xF4\xF6\xF5\xFA\xF9\xFB\xFC\u2020\xB0\xA2\xA3\xA7\u2022\xB6\xDF\xAE\u0160\u2122\xB4\xA8\u2260\u017D\xD8\u221E\xB1\u2264\u2265\u2206\xB5\u2202\u2211\u220F\u0161\u222B\xAA\xBA\u03A9\u017E\xF8\xBF\xA1\xAC\u221A\u0192\u2248\u0106\xAB\u010C\u2026\xA0\xC0\xC3\xD5\u0152\u0153\u0110\u2014\u201C\u201D\u2018\u2019\xF7\u25CA\uF8FF\xA9\u2044\u20AC\u2039\u203A\xC6\xBB\u2013\xB7\u201A\u201E\u2030\xC2\u0107\xC1\u010D\xC8\xCD\xCE\xCF\xCC\xD3\xD4\u0111\xD2\xDA\xDB\xD9\u0131\u02C6\u02DC\xAF\u03C0\xCB\u02DA\xB8\xCA\xE6\u02C7"
    ),
    "x-mac-cyrillic": (
      // Python: 'mac_cyrillic'
      "\u0410\u0411\u0412\u0413\u0414\u0415\u0416\u0417\u0418\u0419\u041A\u041B\u041C\u041D\u041E\u041F\u0420\u0421\u0422\u0423\u0424\u0425\u0426\u0427\u0428\u0429\u042A\u042B\u042C\u042D\u042E\u042F\u2020\xB0\u0490\xA3\xA7\u2022\xB6\u0406\xAE\xA9\u2122\u0402\u0452\u2260\u0403\u0453\u221E\xB1\u2264\u2265\u0456\xB5\u0491\u0408\u0404\u0454\u0407\u0457\u0409\u0459\u040A\u045A\u0458\u0405\xAC\u221A\u0192\u2248\u2206\xAB\xBB\u2026\xA0\u040B\u045B\u040C\u045C\u0455\u2013\u2014\u201C\u201D\u2018\u2019\xF7\u201E\u040E\u045E\u040F\u045F\u2116\u0401\u0451\u044F\u0430\u0431\u0432\u0433\u0434\u0435\u0436\u0437\u0438\u0439\u043A\u043B\u043C\u043D\u043E\u043F\u0440\u0441\u0442\u0443\u0444\u0445\u0446\u0447\u0448\u0449\u044A\u044B\u044C\u044D\u044E"
    ),
    "x-mac-gaelic": (
      // http://unicode.org/Public/MAPPINGS/VENDORS/APPLE/GAELIC.TXT
      "\xC4\xC5\xC7\xC9\xD1\xD6\xDC\xE1\xE0\xE2\xE4\xE3\xE5\xE7\xE9\xE8\xEA\xEB\xED\xEC\xEE\xEF\xF1\xF3\xF2\xF4\xF6\xF5\xFA\xF9\xFB\xFC\u2020\xB0\xA2\xA3\xA7\u2022\xB6\xDF\xAE\xA9\u2122\xB4\xA8\u2260\xC6\xD8\u1E02\xB1\u2264\u2265\u1E03\u010A\u010B\u1E0A\u1E0B\u1E1E\u1E1F\u0120\u0121\u1E40\xE6\xF8\u1E41\u1E56\u1E57\u027C\u0192\u017F\u1E60\xAB\xBB\u2026\xA0\xC0\xC3\xD5\u0152\u0153\u2013\u2014\u201C\u201D\u2018\u2019\u1E61\u1E9B\xFF\u0178\u1E6A\u20AC\u2039\u203A\u0176\u0177\u1E6B\xB7\u1EF2\u1EF3\u204A\xC2\xCA\xC1\xCB\xC8\xCD\xCE\xCF\xCC\xD3\xD4\u2663\xD2\xDA\xDB\xD9\u0131\xDD\xFD\u0174\u0175\u1E84\u1E85\u1E80\u1E81\u1E82\u1E83"
    ),
    "x-mac-greek": (
      // Python: 'mac_greek'
      "\xC4\xB9\xB2\xC9\xB3\xD6\xDC\u0385\xE0\xE2\xE4\u0384\xA8\xE7\xE9\xE8\xEA\xEB\xA3\u2122\xEE\xEF\u2022\xBD\u2030\xF4\xF6\xA6\u20AC\xF9\xFB\xFC\u2020\u0393\u0394\u0398\u039B\u039E\u03A0\xDF\xAE\xA9\u03A3\u03AA\xA7\u2260\xB0\xB7\u0391\xB1\u2264\u2265\xA5\u0392\u0395\u0396\u0397\u0399\u039A\u039C\u03A6\u03AB\u03A8\u03A9\u03AC\u039D\xAC\u039F\u03A1\u2248\u03A4\xAB\xBB\u2026\xA0\u03A5\u03A7\u0386\u0388\u0153\u2013\u2015\u201C\u201D\u2018\u2019\xF7\u0389\u038A\u038C\u038E\u03AD\u03AE\u03AF\u03CC\u038F\u03CD\u03B1\u03B2\u03C8\u03B4\u03B5\u03C6\u03B3\u03B7\u03B9\u03BE\u03BA\u03BB\u03BC\u03BD\u03BF\u03C0\u03CE\u03C1\u03C3\u03C4\u03B8\u03C9\u03C2\u03C7\u03C5\u03B6\u03CA\u03CB\u0390\u03B0\xAD"
    ),
    "x-mac-icelandic": (
      // Python: 'mac_iceland'
      "\xC4\xC5\xC7\xC9\xD1\xD6\xDC\xE1\xE0\xE2\xE4\xE3\xE5\xE7\xE9\xE8\xEA\xEB\xED\xEC\xEE\xEF\xF1\xF3\xF2\xF4\xF6\xF5\xFA\xF9\xFB\xFC\xDD\xB0\xA2\xA3\xA7\u2022\xB6\xDF\xAE\xA9\u2122\xB4\xA8\u2260\xC6\xD8\u221E\xB1\u2264\u2265\xA5\xB5\u2202\u2211\u220F\u03C0\u222B\xAA\xBA\u03A9\xE6\xF8\xBF\xA1\xAC\u221A\u0192\u2248\u2206\xAB\xBB\u2026\xA0\xC0\xC3\xD5\u0152\u0153\u2013\u2014\u201C\u201D\u2018\u2019\xF7\u25CA\xFF\u0178\u2044\u20AC\xD0\xF0\xDE\xFE\xFD\xB7\u201A\u201E\u2030\xC2\xCA\xC1\xCB\xC8\xCD\xCE\xCF\xCC\xD3\xD4\uF8FF\xD2\xDA\xDB\xD9\u0131\u02C6\u02DC\xAF\u02D8\u02D9\u02DA\xB8\u02DD\u02DB\u02C7"
    ),
    "x-mac-inuit": (
      // http://unicode.org/Public/MAPPINGS/VENDORS/APPLE/INUIT.TXT
      "\u1403\u1404\u1405\u1406\u140A\u140B\u1431\u1432\u1433\u1434\u1438\u1439\u1449\u144E\u144F\u1450\u1451\u1455\u1456\u1466\u146D\u146E\u146F\u1470\u1472\u1473\u1483\u148B\u148C\u148D\u148E\u1490\u1491\xB0\u14A1\u14A5\u14A6\u2022\xB6\u14A7\xAE\xA9\u2122\u14A8\u14AA\u14AB\u14BB\u14C2\u14C3\u14C4\u14C5\u14C7\u14C8\u14D0\u14EF\u14F0\u14F1\u14F2\u14F4\u14F5\u1505\u14D5\u14D6\u14D7\u14D8\u14DA\u14DB\u14EA\u1528\u1529\u152A\u152B\u152D\u2026\xA0\u152E\u153E\u1555\u1556\u1557\u2013\u2014\u201C\u201D\u2018\u2019\u1558\u1559\u155A\u155D\u1546\u1547\u1548\u1549\u154B\u154C\u1550\u157F\u1580\u1581\u1582\u1583\u1584\u1585\u158F\u1590\u1591\u1592\u1593\u1594\u1595\u1671\u1672\u1673\u1674\u1675\u1676\u1596\u15A0\u15A1\u15A2\u15A3\u15A4\u15A5\u15A6\u157C\u0141\u0142"
    ),
    "x-mac-ce": (
      // Python: 'mac_latin2'
      "\xC4\u0100\u0101\xC9\u0104\xD6\xDC\xE1\u0105\u010C\xE4\u010D\u0106\u0107\xE9\u0179\u017A\u010E\xED\u010F\u0112\u0113\u0116\xF3\u0117\xF4\xF6\xF5\xFA\u011A\u011B\xFC\u2020\xB0\u0118\xA3\xA7\u2022\xB6\xDF\xAE\xA9\u2122\u0119\xA8\u2260\u0123\u012E\u012F\u012A\u2264\u2265\u012B\u0136\u2202\u2211\u0142\u013B\u013C\u013D\u013E\u0139\u013A\u0145\u0146\u0143\xAC\u221A\u0144\u0147\u2206\xAB\xBB\u2026\xA0\u0148\u0150\xD5\u0151\u014C\u2013\u2014\u201C\u201D\u2018\u2019\xF7\u25CA\u014D\u0154\u0155\u0158\u2039\u203A\u0159\u0156\u0157\u0160\u201A\u201E\u0161\u015A\u015B\xC1\u0164\u0165\xCD\u017D\u017E\u016A\xD3\xD4\u016B\u016E\xDA\u016F\u0170\u0171\u0172\u0173\xDD\xFD\u0137\u017B\u0141\u017C\u0122\u02C7"
    ),
    macintosh: (
      // Python: 'mac_roman'
      "\xC4\xC5\xC7\xC9\xD1\xD6\xDC\xE1\xE0\xE2\xE4\xE3\xE5\xE7\xE9\xE8\xEA\xEB\xED\xEC\xEE\xEF\xF1\xF3\xF2\xF4\xF6\xF5\xFA\xF9\xFB\xFC\u2020\xB0\xA2\xA3\xA7\u2022\xB6\xDF\xAE\xA9\u2122\xB4\xA8\u2260\xC6\xD8\u221E\xB1\u2264\u2265\xA5\xB5\u2202\u2211\u220F\u03C0\u222B\xAA\xBA\u03A9\xE6\xF8\xBF\xA1\xAC\u221A\u0192\u2248\u2206\xAB\xBB\u2026\xA0\xC0\xC3\xD5\u0152\u0153\u2013\u2014\u201C\u201D\u2018\u2019\xF7\u25CA\xFF\u0178\u2044\u20AC\u2039\u203A\uFB01\uFB02\u2021\xB7\u201A\u201E\u2030\xC2\xCA\xC1\xCB\xC8\xCD\xCE\xCF\xCC\xD3\xD4\uF8FF\xD2\xDA\xDB\xD9\u0131\u02C6\u02DC\xAF\u02D8\u02D9\u02DA\xB8\u02DD\u02DB\u02C7"
    ),
    "x-mac-romanian": (
      // Python: 'mac_romanian'
      "\xC4\xC5\xC7\xC9\xD1\xD6\xDC\xE1\xE0\xE2\xE4\xE3\xE5\xE7\xE9\xE8\xEA\xEB\xED\xEC\xEE\xEF\xF1\xF3\xF2\xF4\xF6\xF5\xFA\xF9\xFB\xFC\u2020\xB0\xA2\xA3\xA7\u2022\xB6\xDF\xAE\xA9\u2122\xB4\xA8\u2260\u0102\u0218\u221E\xB1\u2264\u2265\xA5\xB5\u2202\u2211\u220F\u03C0\u222B\xAA\xBA\u03A9\u0103\u0219\xBF\xA1\xAC\u221A\u0192\u2248\u2206\xAB\xBB\u2026\xA0\xC0\xC3\xD5\u0152\u0153\u2013\u2014\u201C\u201D\u2018\u2019\xF7\u25CA\xFF\u0178\u2044\u20AC\u2039\u203A\u021A\u021B\u2021\xB7\u201A\u201E\u2030\xC2\xCA\xC1\xCB\xC8\xCD\xCE\xCF\xCC\xD3\xD4\uF8FF\xD2\xDA\xDB\xD9\u0131\u02C6\u02DC\xAF\u02D8\u02D9\u02DA\xB8\u02DD\u02DB\u02C7"
    ),
    "x-mac-turkish": (
      // Python: 'mac_turkish'
      "\xC4\xC5\xC7\xC9\xD1\xD6\xDC\xE1\xE0\xE2\xE4\xE3\xE5\xE7\xE9\xE8\xEA\xEB\xED\xEC\xEE\xEF\xF1\xF3\xF2\xF4\xF6\xF5\xFA\xF9\xFB\xFC\u2020\xB0\xA2\xA3\xA7\u2022\xB6\xDF\xAE\xA9\u2122\xB4\xA8\u2260\xC6\xD8\u221E\xB1\u2264\u2265\xA5\xB5\u2202\u2211\u220F\u03C0\u222B\xAA\xBA\u03A9\xE6\xF8\xBF\xA1\xAC\u221A\u0192\u2248\u2206\xAB\xBB\u2026\xA0\xC0\xC3\xD5\u0152\u0153\u2013\u2014\u201C\u201D\u2018\u2019\xF7\u25CA\xFF\u0178\u011E\u011F\u0130\u0131\u015E\u015F\u2021\xB7\u201A\u201E\u2030\xC2\xCA\xC1\xCB\xC8\xCD\xCE\xCF\xCC\xD3\xD4\uF8FF\xD2\xDA\xDB\xD9\uF8A0\u02C6\u02DC\xAF\u02D8\u02D9\u02DA\xB8\u02DD\u02DB\u02C7"
    )
  };
  decode.MACSTRING = function(dataView, offset, dataLength, encoding) {
    var table2 = eightBitMacEncodings[encoding];
    if (table2 === void 0) {
      return void 0;
    }
    var result = "";
    for (var i = 0; i < dataLength; i++) {
      var c = dataView.getUint8(offset + i);
      if (c <= 127) {
        result += String.fromCharCode(c);
      } else {
        result += table2[c & 127];
      }
    }
    return result;
  };
  var macEncodingTableCache = typeof WeakMap === "function" && /* @__PURE__ */ new WeakMap();
  var macEncodingCacheKeys;
  var getMacEncodingTable = function(encoding) {
    if (!macEncodingCacheKeys) {
      macEncodingCacheKeys = {};
      for (var e in eightBitMacEncodings) {
        macEncodingCacheKeys[e] = new String(e);
      }
    }
    var cacheKey = macEncodingCacheKeys[encoding];
    if (cacheKey === void 0) {
      return void 0;
    }
    if (macEncodingTableCache) {
      var cachedTable = macEncodingTableCache.get(cacheKey);
      if (cachedTable !== void 0) {
        return cachedTable;
      }
    }
    var decodingTable = eightBitMacEncodings[encoding];
    if (decodingTable === void 0) {
      return void 0;
    }
    var encodingTable = {};
    for (var i = 0; i < decodingTable.length; i++) {
      encodingTable[decodingTable.charCodeAt(i)] = i + 128;
    }
    if (macEncodingTableCache) {
      macEncodingTableCache.set(cacheKey, encodingTable);
    }
    return encodingTable;
  };
  encode.MACSTRING = function(str, encoding) {
    var table2 = getMacEncodingTable(encoding);
    if (table2 === void 0) {
      return void 0;
    }
    var result = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c >= 128) {
        c = table2[c];
        if (c === void 0) {
          return void 0;
        }
      }
      result[i] = c;
    }
    return result;
  };
  sizeOf.MACSTRING = function(str, encoding) {
    var b = encode.MACSTRING(str, encoding);
    if (b !== void 0) {
      return b.length;
    } else {
      return 0;
    }
  };
  function isByteEncodable(value) {
    return value >= -128 && value <= 127;
  }
  function encodeVarDeltaRunAsZeroes(deltas, pos, result) {
    var runLength = 0;
    var numDeltas = deltas.length;
    while (pos < numDeltas && runLength < 64 && deltas[pos] === 0) {
      ++pos;
      ++runLength;
    }
    result.push(128 | runLength - 1);
    return pos;
  }
  function encodeVarDeltaRunAsBytes(deltas, offset, result) {
    var runLength = 0;
    var numDeltas = deltas.length;
    var pos = offset;
    while (pos < numDeltas && runLength < 64) {
      var value = deltas[pos];
      if (!isByteEncodable(value)) {
        break;
      }
      if (value === 0 && pos + 1 < numDeltas && deltas[pos + 1] === 0) {
        break;
      }
      ++pos;
      ++runLength;
    }
    result.push(runLength - 1);
    for (var i = offset; i < pos; ++i) {
      result.push(deltas[i] + 256 & 255);
    }
    return pos;
  }
  function encodeVarDeltaRunAsWords(deltas, offset, result) {
    var runLength = 0;
    var numDeltas = deltas.length;
    var pos = offset;
    while (pos < numDeltas && runLength < 64) {
      var value = deltas[pos];
      if (value === 0) {
        break;
      }
      if (isByteEncodable(value) && pos + 1 < numDeltas && isByteEncodable(deltas[pos + 1])) {
        break;
      }
      ++pos;
      ++runLength;
    }
    result.push(64 | runLength - 1);
    for (var i = offset; i < pos; ++i) {
      var val = deltas[i];
      result.push(val + 65536 >> 8 & 255, val + 256 & 255);
    }
    return pos;
  }
  encode.VARDELTAS = function(deltas) {
    var pos = 0;
    var result = [];
    while (pos < deltas.length) {
      var value = deltas[pos];
      if (value === 0) {
        pos = encodeVarDeltaRunAsZeroes(deltas, pos, result);
      } else if (value >= -128 && value <= 127) {
        pos = encodeVarDeltaRunAsBytes(deltas, pos, result);
      } else {
        pos = encodeVarDeltaRunAsWords(deltas, pos, result);
      }
    }
    return result;
  };
  encode.INDEX = function(l) {
    var offset = 1;
    var offsets = [offset];
    var data = [];
    for (var i = 0; i < l.length; i += 1) {
      var v = encode.OBJECT(l[i]);
      Array.prototype.push.apply(data, v);
      offset += v.length;
      offsets.push(offset);
    }
    if (data.length === 0) {
      return [0, 0];
    }
    var encodedOffsets = [];
    var offSize = 1 + Math.floor(Math.log(offset) / Math.log(2)) / 8 | 0;
    var offsetEncoder = [void 0, encode.BYTE, encode.USHORT, encode.UINT24, encode.ULONG][offSize];
    for (var i$1 = 0; i$1 < offsets.length; i$1 += 1) {
      var encodedOffset = offsetEncoder(offsets[i$1]);
      Array.prototype.push.apply(encodedOffsets, encodedOffset);
    }
    return Array.prototype.concat(
      encode.Card16(l.length),
      encode.OffSize(offSize),
      encodedOffsets,
      data
    );
  };
  sizeOf.INDEX = function(v) {
    return encode.INDEX(v).length;
  };
  encode.DICT = function(m) {
    var d = [];
    var keys = Object.keys(m);
    var length = keys.length;
    for (var i = 0; i < length; i += 1) {
      var k = parseInt(keys[i], 0);
      var v = m[k];
      d = d.concat(encode.OPERAND(v.value, v.type));
      d = d.concat(encode.OPERATOR(k));
    }
    return d;
  };
  sizeOf.DICT = function(m) {
    return encode.DICT(m).length;
  };
  encode.OPERATOR = function(v) {
    if (v < 1200) {
      return [v];
    } else {
      return [12, v - 1200];
    }
  };
  encode.OPERAND = function(v, type) {
    var d = [];
    if (Array.isArray(type)) {
      for (var i = 0; i < type.length; i += 1) {
        check.argument(v.length === type.length, "Not enough arguments given for type" + type);
        d = d.concat(encode.OPERAND(v[i], type[i]));
      }
    } else {
      if (type === "SID") {
        d = d.concat(encode.NUMBER(v));
      } else if (type === "offset") {
        d = d.concat(encode.NUMBER32(v));
      } else if (type === "number") {
        d = d.concat(encode.NUMBER(v));
      } else if (type === "real") {
        d = d.concat(encode.REAL(v));
      } else {
        throw new Error("Unknown operand type " + type);
      }
    }
    return d;
  };
  encode.OP = encode.BYTE;
  sizeOf.OP = sizeOf.BYTE;
  var wmm = typeof WeakMap === "function" && /* @__PURE__ */ new WeakMap();
  encode.CHARSTRING = function(ops) {
    if (wmm) {
      var cachedValue = wmm.get(ops);
      if (cachedValue !== void 0) {
        return cachedValue;
      }
    }
    var d = [];
    var length = ops.length;
    for (var i = 0; i < length; i += 1) {
      var op = ops[i];
      d = d.concat(encode[op.type](op.value));
    }
    if (wmm) {
      wmm.set(ops, d);
    }
    return d;
  };
  sizeOf.CHARSTRING = function(ops) {
    return encode.CHARSTRING(ops).length;
  };
  encode.OBJECT = function(v) {
    var encodingFunction = encode[v.type];
    check.argument(encodingFunction !== void 0, "No encoding function for type " + v.type);
    return encodingFunction(v.value);
  };
  sizeOf.OBJECT = function(v) {
    var sizeOfFunction = sizeOf[v.type];
    check.argument(sizeOfFunction !== void 0, "No sizeOf function for type " + v.type);
    return sizeOfFunction(v.value);
  };
  encode.TABLE = function(table2) {
    var d = [];
    var length = table2.fields.length;
    var subtables = [];
    var subtableOffsets = [];
    for (var i = 0; i < length; i += 1) {
      var field = table2.fields[i];
      var encodingFunction = encode[field.type];
      check.argument(encodingFunction !== void 0, "No encoding function for field type " + field.type + " (" + field.name + ")");
      var value = table2[field.name];
      if (value === void 0) {
        value = field.value;
      }
      var bytes = encodingFunction(value);
      if (field.type === "TABLE") {
        subtableOffsets.push(d.length);
        d = d.concat([0, 0]);
        subtables.push(bytes);
      } else {
        d = d.concat(bytes);
      }
    }
    for (var i$1 = 0; i$1 < subtables.length; i$1 += 1) {
      var o = subtableOffsets[i$1];
      var offset = d.length;
      check.argument(offset < 65536, "Table " + table2.tableName + " too big.");
      d[o] = offset >> 8;
      d[o + 1] = offset & 255;
      d = d.concat(subtables[i$1]);
    }
    return d;
  };
  sizeOf.TABLE = function(table2) {
    var numBytes = 0;
    var length = table2.fields.length;
    for (var i = 0; i < length; i += 1) {
      var field = table2.fields[i];
      var sizeOfFunction = sizeOf[field.type];
      check.argument(sizeOfFunction !== void 0, "No sizeOf function for field type " + field.type + " (" + field.name + ")");
      var value = table2[field.name];
      if (value === void 0) {
        value = field.value;
      }
      numBytes += sizeOfFunction(value);
      if (field.type === "TABLE") {
        numBytes += 2;
      }
    }
    return numBytes;
  };
  encode.RECORD = encode.TABLE;
  sizeOf.RECORD = sizeOf.TABLE;
  encode.LITERAL = function(v) {
    return v;
  };
  sizeOf.LITERAL = function(v) {
    return v.length;
  };
  function Table(tableName, fields, options) {
    if (fields.length && (fields[0].name !== "coverageFormat" || fields[0].value === 1)) {
      for (var i = 0; i < fields.length; i += 1) {
        var field = fields[i];
        this[field.name] = field.value;
      }
    }
    this.tableName = tableName;
    this.fields = fields;
    if (options) {
      var optionKeys = Object.keys(options);
      for (var i$1 = 0; i$1 < optionKeys.length; i$1 += 1) {
        var k = optionKeys[i$1];
        var v = options[k];
        if (this[k] !== void 0) {
          this[k] = v;
        }
      }
    }
  }
  Table.prototype.encode = function() {
    return encode.TABLE(this);
  };
  Table.prototype.sizeOf = function() {
    return sizeOf.TABLE(this);
  };
  function ushortList(itemName, list, count) {
    if (count === void 0) {
      count = list.length;
    }
    var fields = new Array(list.length + 1);
    fields[0] = { name: itemName + "Count", type: "USHORT", value: count };
    for (var i = 0; i < list.length; i++) {
      fields[i + 1] = { name: itemName + i, type: "USHORT", value: list[i] };
    }
    return fields;
  }
  function tableList(itemName, records, itemCallback) {
    var count = records.length;
    var fields = new Array(count + 1);
    fields[0] = { name: itemName + "Count", type: "USHORT", value: count };
    for (var i = 0; i < count; i++) {
      fields[i + 1] = { name: itemName + i, type: "TABLE", value: itemCallback(records[i], i) };
    }
    return fields;
  }
  function recordList(itemName, records, itemCallback) {
    var count = records.length;
    var fields = [];
    fields[0] = { name: itemName + "Count", type: "USHORT", value: count };
    for (var i = 0; i < count; i++) {
      fields = fields.concat(itemCallback(records[i], i));
    }
    return fields;
  }
  function Coverage(coverageTable) {
    if (coverageTable.format === 1) {
      Table.call(
        this,
        "coverageTable",
        [{ name: "coverageFormat", type: "USHORT", value: 1 }].concat(ushortList("glyph", coverageTable.glyphs))
      );
    } else if (coverageTable.format === 2) {
      Table.call(
        this,
        "coverageTable",
        [{ name: "coverageFormat", type: "USHORT", value: 2 }].concat(recordList("rangeRecord", coverageTable.ranges, function(RangeRecord) {
          return [
            { name: "startGlyphID", type: "USHORT", value: RangeRecord.start },
            { name: "endGlyphID", type: "USHORT", value: RangeRecord.end },
            { name: "startCoverageIndex", type: "USHORT", value: RangeRecord.index }
          ];
        }))
      );
    } else {
      check.assert(false, "Coverage format must be 1 or 2.");
    }
  }
  Coverage.prototype = Object.create(Table.prototype);
  Coverage.prototype.constructor = Coverage;
  function ScriptList(scriptListTable) {
    Table.call(
      this,
      "scriptListTable",
      recordList("scriptRecord", scriptListTable, function(scriptRecord, i) {
        var script = scriptRecord.script;
        var defaultLangSys = script.defaultLangSys;
        check.assert(!!defaultLangSys, "Unable to write GSUB: script " + scriptRecord.tag + " has no default language system.");
        return [
          { name: "scriptTag" + i, type: "TAG", value: scriptRecord.tag },
          { name: "script" + i, type: "TABLE", value: new Table("scriptTable", [
            { name: "defaultLangSys", type: "TABLE", value: new Table("defaultLangSys", [
              { name: "lookupOrder", type: "USHORT", value: 0 },
              { name: "reqFeatureIndex", type: "USHORT", value: defaultLangSys.reqFeatureIndex }
            ].concat(ushortList("featureIndex", defaultLangSys.featureIndexes))) }
          ].concat(recordList("langSys", script.langSysRecords, function(langSysRecord, i2) {
            var langSys = langSysRecord.langSys;
            return [
              { name: "langSysTag" + i2, type: "TAG", value: langSysRecord.tag },
              { name: "langSys" + i2, type: "TABLE", value: new Table("langSys", [
                { name: "lookupOrder", type: "USHORT", value: 0 },
                { name: "reqFeatureIndex", type: "USHORT", value: langSys.reqFeatureIndex }
              ].concat(ushortList("featureIndex", langSys.featureIndexes))) }
            ];
          }))) }
        ];
      })
    );
  }
  ScriptList.prototype = Object.create(Table.prototype);
  ScriptList.prototype.constructor = ScriptList;
  function FeatureList(featureListTable) {
    Table.call(
      this,
      "featureListTable",
      recordList("featureRecord", featureListTable, function(featureRecord, i) {
        var feature = featureRecord.feature;
        return [
          { name: "featureTag" + i, type: "TAG", value: featureRecord.tag },
          { name: "feature" + i, type: "TABLE", value: new Table("featureTable", [
            { name: "featureParams", type: "USHORT", value: feature.featureParams }
          ].concat(ushortList("lookupListIndex", feature.lookupListIndexes))) }
        ];
      })
    );
  }
  FeatureList.prototype = Object.create(Table.prototype);
  FeatureList.prototype.constructor = FeatureList;
  function LookupList(lookupListTable, subtableMakers2) {
    Table.call(this, "lookupListTable", tableList("lookup", lookupListTable, function(lookupTable) {
      var subtableCallback = subtableMakers2[lookupTable.lookupType];
      check.assert(!!subtableCallback, "Unable to write GSUB lookup type " + lookupTable.lookupType + " tables.");
      return new Table("lookupTable", [
        { name: "lookupType", type: "USHORT", value: lookupTable.lookupType },
        { name: "lookupFlag", type: "USHORT", value: lookupTable.lookupFlag }
      ].concat(tableList("subtable", lookupTable.subtables, subtableCallback)));
    }));
  }
  LookupList.prototype = Object.create(Table.prototype);
  LookupList.prototype.constructor = LookupList;
  var table = {
    Table,
    Record: Table,
    Coverage,
    ScriptList,
    FeatureList,
    LookupList,
    ushortList,
    tableList,
    recordList
  };
  function getByte(dataView, offset) {
    return dataView.getUint8(offset);
  }
  function getUShort(dataView, offset) {
    return dataView.getUint16(offset, false);
  }
  function getShort(dataView, offset) {
    return dataView.getInt16(offset, false);
  }
  function getULong(dataView, offset) {
    return dataView.getUint32(offset, false);
  }
  function getFixed(dataView, offset) {
    var decimal = dataView.getInt16(offset, false);
    var fraction = dataView.getUint16(offset + 2, false);
    return decimal + fraction / 65535;
  }
  function getTag(dataView, offset) {
    var tag = "";
    for (var i = offset; i < offset + 4; i += 1) {
      tag += String.fromCharCode(dataView.getInt8(i));
    }
    return tag;
  }
  function getOffset(dataView, offset, offSize) {
    var v = 0;
    for (var i = 0; i < offSize; i += 1) {
      v <<= 8;
      v += dataView.getUint8(offset + i);
    }
    return v;
  }
  function getBytes(dataView, startOffset, endOffset) {
    var bytes = [];
    for (var i = startOffset; i < endOffset; i += 1) {
      bytes.push(dataView.getUint8(i));
    }
    return bytes;
  }
  function bytesToString(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i += 1) {
      s += String.fromCharCode(bytes[i]);
    }
    return s;
  }
  var typeOffsets = {
    byte: 1,
    uShort: 2,
    short: 2,
    uLong: 4,
    fixed: 4,
    longDateTime: 8,
    tag: 4
  };
  function Parser2(data, offset) {
    this.data = data;
    this.offset = offset;
    this.relativeOffset = 0;
  }
  Parser2.prototype.parseByte = function() {
    var v = this.data.getUint8(this.offset + this.relativeOffset);
    this.relativeOffset += 1;
    return v;
  };
  Parser2.prototype.parseChar = function() {
    var v = this.data.getInt8(this.offset + this.relativeOffset);
    this.relativeOffset += 1;
    return v;
  };
  Parser2.prototype.parseCard8 = Parser2.prototype.parseByte;
  Parser2.prototype.parseUShort = function() {
    var v = this.data.getUint16(this.offset + this.relativeOffset);
    this.relativeOffset += 2;
    return v;
  };
  Parser2.prototype.parseCard16 = Parser2.prototype.parseUShort;
  Parser2.prototype.parseSID = Parser2.prototype.parseUShort;
  Parser2.prototype.parseOffset16 = Parser2.prototype.parseUShort;
  Parser2.prototype.parseShort = function() {
    var v = this.data.getInt16(this.offset + this.relativeOffset);
    this.relativeOffset += 2;
    return v;
  };
  Parser2.prototype.parseF2Dot14 = function() {
    var v = this.data.getInt16(this.offset + this.relativeOffset) / 16384;
    this.relativeOffset += 2;
    return v;
  };
  Parser2.prototype.parseULong = function() {
    var v = getULong(this.data, this.offset + this.relativeOffset);
    this.relativeOffset += 4;
    return v;
  };
  Parser2.prototype.parseOffset32 = Parser2.prototype.parseULong;
  Parser2.prototype.parseFixed = function() {
    var v = getFixed(this.data, this.offset + this.relativeOffset);
    this.relativeOffset += 4;
    return v;
  };
  Parser2.prototype.parseString = function(length) {
    var dataView = this.data;
    var offset = this.offset + this.relativeOffset;
    var string = "";
    this.relativeOffset += length;
    for (var i = 0; i < length; i++) {
      string += String.fromCharCode(dataView.getUint8(offset + i));
    }
    return string;
  };
  Parser2.prototype.parseTag = function() {
    return this.parseString(4);
  };
  Parser2.prototype.parseLongDateTime = function() {
    var v = getULong(this.data, this.offset + this.relativeOffset + 4);
    v -= 2082844800;
    this.relativeOffset += 8;
    return v;
  };
  Parser2.prototype.parseVersion = function(minorBase) {
    var major = getUShort(this.data, this.offset + this.relativeOffset);
    var minor = getUShort(this.data, this.offset + this.relativeOffset + 2);
    this.relativeOffset += 4;
    if (minorBase === void 0) {
      minorBase = 4096;
    }
    return major + minor / minorBase / 10;
  };
  Parser2.prototype.skip = function(type, amount) {
    if (amount === void 0) {
      amount = 1;
    }
    this.relativeOffset += typeOffsets[type] * amount;
  };
  Parser2.prototype.parseULongList = function(count) {
    if (count === void 0) {
      count = this.parseULong();
    }
    var offsets = new Array(count);
    var dataView = this.data;
    var offset = this.offset + this.relativeOffset;
    for (var i = 0; i < count; i++) {
      offsets[i] = dataView.getUint32(offset);
      offset += 4;
    }
    this.relativeOffset += count * 4;
    return offsets;
  };
  Parser2.prototype.parseOffset16List = Parser2.prototype.parseUShortList = function(count) {
    if (count === void 0) {
      count = this.parseUShort();
    }
    var offsets = new Array(count);
    var dataView = this.data;
    var offset = this.offset + this.relativeOffset;
    for (var i = 0; i < count; i++) {
      offsets[i] = dataView.getUint16(offset);
      offset += 2;
    }
    this.relativeOffset += count * 2;
    return offsets;
  };
  Parser2.prototype.parseShortList = function(count) {
    var list = new Array(count);
    var dataView = this.data;
    var offset = this.offset + this.relativeOffset;
    for (var i = 0; i < count; i++) {
      list[i] = dataView.getInt16(offset);
      offset += 2;
    }
    this.relativeOffset += count * 2;
    return list;
  };
  Parser2.prototype.parseByteList = function(count) {
    var list = new Array(count);
    var dataView = this.data;
    var offset = this.offset + this.relativeOffset;
    for (var i = 0; i < count; i++) {
      list[i] = dataView.getUint8(offset++);
    }
    this.relativeOffset += count;
    return list;
  };
  Parser2.prototype.parseList = function(count, itemCallback) {
    if (!itemCallback) {
      itemCallback = count;
      count = this.parseUShort();
    }
    var list = new Array(count);
    for (var i = 0; i < count; i++) {
      list[i] = itemCallback.call(this);
    }
    return list;
  };
  Parser2.prototype.parseList32 = function(count, itemCallback) {
    if (!itemCallback) {
      itemCallback = count;
      count = this.parseULong();
    }
    var list = new Array(count);
    for (var i = 0; i < count; i++) {
      list[i] = itemCallback.call(this);
    }
    return list;
  };
  Parser2.prototype.parseRecordList = function(count, recordDescription) {
    if (!recordDescription) {
      recordDescription = count;
      count = this.parseUShort();
    }
    var records = new Array(count);
    var fields = Object.keys(recordDescription);
    for (var i = 0; i < count; i++) {
      var rec = {};
      for (var j = 0; j < fields.length; j++) {
        var fieldName = fields[j];
        var fieldType = recordDescription[fieldName];
        rec[fieldName] = fieldType.call(this);
      }
      records[i] = rec;
    }
    return records;
  };
  Parser2.prototype.parseRecordList32 = function(count, recordDescription) {
    if (!recordDescription) {
      recordDescription = count;
      count = this.parseULong();
    }
    var records = new Array(count);
    var fields = Object.keys(recordDescription);
    for (var i = 0; i < count; i++) {
      var rec = {};
      for (var j = 0; j < fields.length; j++) {
        var fieldName = fields[j];
        var fieldType = recordDescription[fieldName];
        rec[fieldName] = fieldType.call(this);
      }
      records[i] = rec;
    }
    return records;
  };
  Parser2.prototype.parseStruct = function(description) {
    if (typeof description === "function") {
      return description.call(this);
    } else {
      var fields = Object.keys(description);
      var struct = {};
      for (var j = 0; j < fields.length; j++) {
        var fieldName = fields[j];
        var fieldType = description[fieldName];
        struct[fieldName] = fieldType.call(this);
      }
      return struct;
    }
  };
  Parser2.prototype.parseValueRecord = function(valueFormat) {
    if (valueFormat === void 0) {
      valueFormat = this.parseUShort();
    }
    if (valueFormat === 0) {
      return;
    }
    var valueRecord = {};
    if (valueFormat & 1) {
      valueRecord.xPlacement = this.parseShort();
    }
    if (valueFormat & 2) {
      valueRecord.yPlacement = this.parseShort();
    }
    if (valueFormat & 4) {
      valueRecord.xAdvance = this.parseShort();
    }
    if (valueFormat & 8) {
      valueRecord.yAdvance = this.parseShort();
    }
    if (valueFormat & 16) {
      valueRecord.xPlaDevice = void 0;
      this.parseShort();
    }
    if (valueFormat & 32) {
      valueRecord.yPlaDevice = void 0;
      this.parseShort();
    }
    if (valueFormat & 64) {
      valueRecord.xAdvDevice = void 0;
      this.parseShort();
    }
    if (valueFormat & 128) {
      valueRecord.yAdvDevice = void 0;
      this.parseShort();
    }
    return valueRecord;
  };
  Parser2.prototype.parseValueRecordList = function() {
    var valueFormat = this.parseUShort();
    var valueCount = this.parseUShort();
    var values = new Array(valueCount);
    for (var i = 0; i < valueCount; i++) {
      values[i] = this.parseValueRecord(valueFormat);
    }
    return values;
  };
  Parser2.prototype.parsePointer = function(description) {
    var structOffset = this.parseOffset16();
    if (structOffset > 0) {
      return new Parser2(this.data, this.offset + structOffset).parseStruct(description);
    }
    return void 0;
  };
  Parser2.prototype.parsePointer32 = function(description) {
    var structOffset = this.parseOffset32();
    if (structOffset > 0) {
      return new Parser2(this.data, this.offset + structOffset).parseStruct(description);
    }
    return void 0;
  };
  Parser2.prototype.parseListOfLists = function(itemCallback) {
    var offsets = this.parseOffset16List();
    var count = offsets.length;
    var relativeOffset = this.relativeOffset;
    var list = new Array(count);
    for (var i = 0; i < count; i++) {
      var start = offsets[i];
      if (start === 0) {
        list[i] = void 0;
        continue;
      }
      this.relativeOffset = start;
      if (itemCallback) {
        var subOffsets = this.parseOffset16List();
        var subList = new Array(subOffsets.length);
        for (var j = 0; j < subOffsets.length; j++) {
          this.relativeOffset = start + subOffsets[j];
          subList[j] = itemCallback.call(this);
        }
        list[i] = subList;
      } else {
        list[i] = this.parseUShortList();
      }
    }
    this.relativeOffset = relativeOffset;
    return list;
  };
  Parser2.prototype.parseCoverage = function() {
    var startOffset = this.offset + this.relativeOffset;
    var format = this.parseUShort();
    var count = this.parseUShort();
    if (format === 1) {
      return {
        format: 1,
        glyphs: this.parseUShortList(count)
      };
    } else if (format === 2) {
      var ranges = new Array(count);
      for (var i = 0; i < count; i++) {
        ranges[i] = {
          start: this.parseUShort(),
          end: this.parseUShort(),
          index: this.parseUShort()
        };
      }
      return {
        format: 2,
        ranges
      };
    }
    throw new Error("0x" + startOffset.toString(16) + ": Coverage format must be 1 or 2.");
  };
  Parser2.prototype.parseClassDef = function() {
    var startOffset = this.offset + this.relativeOffset;
    var format = this.parseUShort();
    if (format === 1) {
      return {
        format: 1,
        startGlyph: this.parseUShort(),
        classes: this.parseUShortList()
      };
    } else if (format === 2) {
      return {
        format: 2,
        ranges: this.parseRecordList({
          start: Parser2.uShort,
          end: Parser2.uShort,
          classId: Parser2.uShort
        })
      };
    }
    throw new Error("0x" + startOffset.toString(16) + ": ClassDef format must be 1 or 2.");
  };
  Parser2.list = function(count, itemCallback) {
    return function() {
      return this.parseList(count, itemCallback);
    };
  };
  Parser2.list32 = function(count, itemCallback) {
    return function() {
      return this.parseList32(count, itemCallback);
    };
  };
  Parser2.recordList = function(count, recordDescription) {
    return function() {
      return this.parseRecordList(count, recordDescription);
    };
  };
  Parser2.recordList32 = function(count, recordDescription) {
    return function() {
      return this.parseRecordList32(count, recordDescription);
    };
  };
  Parser2.pointer = function(description) {
    return function() {
      return this.parsePointer(description);
    };
  };
  Parser2.pointer32 = function(description) {
    return function() {
      return this.parsePointer32(description);
    };
  };
  Parser2.tag = Parser2.prototype.parseTag;
  Parser2.byte = Parser2.prototype.parseByte;
  Parser2.uShort = Parser2.offset16 = Parser2.prototype.parseUShort;
  Parser2.uShortList = Parser2.prototype.parseUShortList;
  Parser2.uLong = Parser2.offset32 = Parser2.prototype.parseULong;
  Parser2.uLongList = Parser2.prototype.parseULongList;
  Parser2.struct = Parser2.prototype.parseStruct;
  Parser2.coverage = Parser2.prototype.parseCoverage;
  Parser2.classDef = Parser2.prototype.parseClassDef;
  var langSysTable = {
    reserved: Parser2.uShort,
    reqFeatureIndex: Parser2.uShort,
    featureIndexes: Parser2.uShortList
  };
  Parser2.prototype.parseScriptList = function() {
    return this.parsePointer(Parser2.recordList({
      tag: Parser2.tag,
      script: Parser2.pointer({
        defaultLangSys: Parser2.pointer(langSysTable),
        langSysRecords: Parser2.recordList({
          tag: Parser2.tag,
          langSys: Parser2.pointer(langSysTable)
        })
      })
    })) || [];
  };
  Parser2.prototype.parseFeatureList = function() {
    return this.parsePointer(Parser2.recordList({
      tag: Parser2.tag,
      feature: Parser2.pointer({
        featureParams: Parser2.offset16,
        lookupListIndexes: Parser2.uShortList
      })
    })) || [];
  };
  Parser2.prototype.parseLookupList = function(lookupTableParsers) {
    return this.parsePointer(Parser2.list(Parser2.pointer(function() {
      var lookupType = this.parseUShort();
      check.argument(1 <= lookupType && lookupType <= 9, "GPOS/GSUB lookup type " + lookupType + " unknown.");
      var lookupFlag = this.parseUShort();
      var useMarkFilteringSet = lookupFlag & 16;
      return {
        lookupType,
        lookupFlag,
        subtables: this.parseList(Parser2.pointer(lookupTableParsers[lookupType])),
        markFilteringSet: useMarkFilteringSet ? this.parseUShort() : void 0
      };
    }))) || [];
  };
  Parser2.prototype.parseFeatureVariationsList = function() {
    return this.parsePointer32(function() {
      var majorVersion = this.parseUShort();
      var minorVersion = this.parseUShort();
      check.argument(majorVersion === 1 && minorVersion < 1, "GPOS/GSUB feature variations table unknown.");
      var featureVariations = this.parseRecordList32({
        conditionSetOffset: Parser2.offset32,
        featureTableSubstitutionOffset: Parser2.offset32
      });
      return featureVariations;
    }) || [];
  };
  var parse = {
    getByte,
    getCard8: getByte,
    getUShort,
    getCard16: getUShort,
    getShort,
    getULong,
    getFixed,
    getTag,
    getOffset,
    getBytes,
    bytesToString,
    Parser: Parser2
  };
  function parseCmapTableFormat12(cmap2, p) {
    p.parseUShort();
    cmap2.length = p.parseULong();
    cmap2.language = p.parseULong();
    var groupCount;
    cmap2.groupCount = groupCount = p.parseULong();
    cmap2.glyphIndexMap = {};
    for (var i = 0; i < groupCount; i += 1) {
      var startCharCode = p.parseULong();
      var endCharCode = p.parseULong();
      var startGlyphId = p.parseULong();
      for (var c = startCharCode; c <= endCharCode; c += 1) {
        cmap2.glyphIndexMap[c] = startGlyphId;
        startGlyphId++;
      }
    }
  }
  function parseCmapTableFormat4(cmap2, p, data, start, offset) {
    cmap2.length = p.parseUShort();
    cmap2.language = p.parseUShort();
    var segCount;
    cmap2.segCount = segCount = p.parseUShort() >> 1;
    p.skip("uShort", 3);
    cmap2.glyphIndexMap = {};
    var endCountParser = new parse.Parser(data, start + offset + 14);
    var startCountParser = new parse.Parser(data, start + offset + 16 + segCount * 2);
    var idDeltaParser = new parse.Parser(data, start + offset + 16 + segCount * 4);
    var idRangeOffsetParser = new parse.Parser(data, start + offset + 16 + segCount * 6);
    var glyphIndexOffset = start + offset + 16 + segCount * 8;
    for (var i = 0; i < segCount - 1; i += 1) {
      var glyphIndex = void 0;
      var endCount = endCountParser.parseUShort();
      var startCount = startCountParser.parseUShort();
      var idDelta = idDeltaParser.parseShort();
      var idRangeOffset = idRangeOffsetParser.parseUShort();
      for (var c = startCount; c <= endCount; c += 1) {
        if (idRangeOffset !== 0) {
          glyphIndexOffset = idRangeOffsetParser.offset + idRangeOffsetParser.relativeOffset - 2;
          glyphIndexOffset += idRangeOffset;
          glyphIndexOffset += (c - startCount) * 2;
          glyphIndex = parse.getUShort(data, glyphIndexOffset);
          if (glyphIndex !== 0) {
            glyphIndex = glyphIndex + idDelta & 65535;
          }
        } else {
          glyphIndex = c + idDelta & 65535;
        }
        cmap2.glyphIndexMap[c] = glyphIndex;
      }
    }
  }
  function parseCmapTable(data, start) {
    var cmap2 = {};
    cmap2.version = parse.getUShort(data, start);
    check.argument(cmap2.version === 0, "cmap table version should be 0.");
    cmap2.numTables = parse.getUShort(data, start + 2);
    var offset = -1;
    for (var i = cmap2.numTables - 1; i >= 0; i -= 1) {
      var platformId = parse.getUShort(data, start + 4 + i * 8);
      var encodingId = parse.getUShort(data, start + 4 + i * 8 + 2);
      if (platformId === 3 && (encodingId === 0 || encodingId === 1 || encodingId === 10) || platformId === 0 && (encodingId === 0 || encodingId === 1 || encodingId === 2 || encodingId === 3 || encodingId === 4)) {
        offset = parse.getULong(data, start + 4 + i * 8 + 4);
        break;
      }
    }
    if (offset === -1) {
      throw new Error("No valid cmap sub-tables found.");
    }
    var p = new parse.Parser(data, start + offset);
    cmap2.format = p.parseUShort();
    if (cmap2.format === 12) {
      parseCmapTableFormat12(cmap2, p);
    } else if (cmap2.format === 4) {
      parseCmapTableFormat4(cmap2, p, data, start, offset);
    } else {
      throw new Error("Only format 4 and 12 cmap tables are supported (found format " + cmap2.format + ").");
    }
    return cmap2;
  }
  function addSegment(t, code, glyphIndex) {
    t.segments.push({
      end: code,
      start: code,
      delta: -(code - glyphIndex),
      offset: 0,
      glyphIndex
    });
  }
  function addTerminatorSegment(t) {
    t.segments.push({
      end: 65535,
      start: 65535,
      delta: 1,
      offset: 0
    });
  }
  function makeCmapTable(glyphs) {
    var isPlan0Only = true;
    var i;
    for (i = glyphs.length - 1; i > 0; i -= 1) {
      var g = glyphs.get(i);
      if (g.unicode > 65535) {
        console.log("Adding CMAP format 12 (needed!)");
        isPlan0Only = false;
        break;
      }
    }
    var cmapTable = [
      { name: "version", type: "USHORT", value: 0 },
      { name: "numTables", type: "USHORT", value: isPlan0Only ? 1 : 2 },
      // CMAP 4 header
      { name: "platformID", type: "USHORT", value: 3 },
      { name: "encodingID", type: "USHORT", value: 1 },
      { name: "offset", type: "ULONG", value: isPlan0Only ? 12 : 12 + 8 }
    ];
    if (!isPlan0Only) {
      cmapTable = cmapTable.concat([
        // CMAP 12 header
        { name: "cmap12PlatformID", type: "USHORT", value: 3 },
        // We encode only for PlatformID = 3 (Windows) because it is supported everywhere
        { name: "cmap12EncodingID", type: "USHORT", value: 10 },
        { name: "cmap12Offset", type: "ULONG", value: 0 }
      ]);
    }
    cmapTable = cmapTable.concat([
      // CMAP 4 Subtable
      { name: "format", type: "USHORT", value: 4 },
      { name: "cmap4Length", type: "USHORT", value: 0 },
      { name: "language", type: "USHORT", value: 0 },
      { name: "segCountX2", type: "USHORT", value: 0 },
      { name: "searchRange", type: "USHORT", value: 0 },
      { name: "entrySelector", type: "USHORT", value: 0 },
      { name: "rangeShift", type: "USHORT", value: 0 }
    ]);
    var t = new table.Table("cmap", cmapTable);
    t.segments = [];
    for (i = 0; i < glyphs.length; i += 1) {
      var glyph = glyphs.get(i);
      for (var j = 0; j < glyph.unicodes.length; j += 1) {
        addSegment(t, glyph.unicodes[j], i);
      }
      t.segments = t.segments.sort(function(a, b) {
        return a.start - b.start;
      });
    }
    addTerminatorSegment(t);
    var segCount = t.segments.length;
    var segCountToRemove = 0;
    var endCounts = [];
    var startCounts = [];
    var idDeltas = [];
    var idRangeOffsets = [];
    var glyphIds = [];
    var cmap12Groups = [];
    for (i = 0; i < segCount; i += 1) {
      var segment = t.segments[i];
      if (segment.end <= 65535 && segment.start <= 65535) {
        endCounts = endCounts.concat({ name: "end_" + i, type: "USHORT", value: segment.end });
        startCounts = startCounts.concat({ name: "start_" + i, type: "USHORT", value: segment.start });
        idDeltas = idDeltas.concat({ name: "idDelta_" + i, type: "SHORT", value: segment.delta });
        idRangeOffsets = idRangeOffsets.concat({ name: "idRangeOffset_" + i, type: "USHORT", value: segment.offset });
        if (segment.glyphId !== void 0) {
          glyphIds = glyphIds.concat({ name: "glyph_" + i, type: "USHORT", value: segment.glyphId });
        }
      } else {
        segCountToRemove += 1;
      }
      if (!isPlan0Only && segment.glyphIndex !== void 0) {
        cmap12Groups = cmap12Groups.concat({ name: "cmap12Start_" + i, type: "ULONG", value: segment.start });
        cmap12Groups = cmap12Groups.concat({ name: "cmap12End_" + i, type: "ULONG", value: segment.end });
        cmap12Groups = cmap12Groups.concat({ name: "cmap12Glyph_" + i, type: "ULONG", value: segment.glyphIndex });
      }
    }
    t.segCountX2 = (segCount - segCountToRemove) * 2;
    t.searchRange = Math.pow(2, Math.floor(Math.log(segCount - segCountToRemove) / Math.log(2))) * 2;
    t.entrySelector = Math.log(t.searchRange / 2) / Math.log(2);
    t.rangeShift = t.segCountX2 - t.searchRange;
    t.fields = t.fields.concat(endCounts);
    t.fields.push({ name: "reservedPad", type: "USHORT", value: 0 });
    t.fields = t.fields.concat(startCounts);
    t.fields = t.fields.concat(idDeltas);
    t.fields = t.fields.concat(idRangeOffsets);
    t.fields = t.fields.concat(glyphIds);
    t.cmap4Length = 14 + // Subtable header
    endCounts.length * 2 + 2 + // reservedPad
    startCounts.length * 2 + idDeltas.length * 2 + idRangeOffsets.length * 2 + glyphIds.length * 2;
    if (!isPlan0Only) {
      var cmap12Length = 16 + // Subtable header
      cmap12Groups.length * 4;
      t.cmap12Offset = 12 + 2 * 2 + 4 + t.cmap4Length;
      t.fields = t.fields.concat([
        { name: "cmap12Format", type: "USHORT", value: 12 },
        { name: "cmap12Reserved", type: "USHORT", value: 0 },
        { name: "cmap12Length", type: "ULONG", value: cmap12Length },
        { name: "cmap12Language", type: "ULONG", value: 0 },
        { name: "cmap12nGroups", type: "ULONG", value: cmap12Groups.length / 3 }
      ]);
      t.fields = t.fields.concat(cmap12Groups);
    }
    return t;
  }
  var cmap = { parse: parseCmapTable, make: makeCmapTable };
  var cffStandardStrings = [
    ".notdef",
    "space",
    "exclam",
    "quotedbl",
    "numbersign",
    "dollar",
    "percent",
    "ampersand",
    "quoteright",
    "parenleft",
    "parenright",
    "asterisk",
    "plus",
    "comma",
    "hyphen",
    "period",
    "slash",
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "colon",
    "semicolon",
    "less",
    "equal",
    "greater",
    "question",
    "at",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    "bracketleft",
    "backslash",
    "bracketright",
    "asciicircum",
    "underscore",
    "quoteleft",
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "s",
    "t",
    "u",
    "v",
    "w",
    "x",
    "y",
    "z",
    "braceleft",
    "bar",
    "braceright",
    "asciitilde",
    "exclamdown",
    "cent",
    "sterling",
    "fraction",
    "yen",
    "florin",
    "section",
    "currency",
    "quotesingle",
    "quotedblleft",
    "guillemotleft",
    "guilsinglleft",
    "guilsinglright",
    "fi",
    "fl",
    "endash",
    "dagger",
    "daggerdbl",
    "periodcentered",
    "paragraph",
    "bullet",
    "quotesinglbase",
    "quotedblbase",
    "quotedblright",
    "guillemotright",
    "ellipsis",
    "perthousand",
    "questiondown",
    "grave",
    "acute",
    "circumflex",
    "tilde",
    "macron",
    "breve",
    "dotaccent",
    "dieresis",
    "ring",
    "cedilla",
    "hungarumlaut",
    "ogonek",
    "caron",
    "emdash",
    "AE",
    "ordfeminine",
    "Lslash",
    "Oslash",
    "OE",
    "ordmasculine",
    "ae",
    "dotlessi",
    "lslash",
    "oslash",
    "oe",
    "germandbls",
    "onesuperior",
    "logicalnot",
    "mu",
    "trademark",
    "Eth",
    "onehalf",
    "plusminus",
    "Thorn",
    "onequarter",
    "divide",
    "brokenbar",
    "degree",
    "thorn",
    "threequarters",
    "twosuperior",
    "registered",
    "minus",
    "eth",
    "multiply",
    "threesuperior",
    "copyright",
    "Aacute",
    "Acircumflex",
    "Adieresis",
    "Agrave",
    "Aring",
    "Atilde",
    "Ccedilla",
    "Eacute",
    "Ecircumflex",
    "Edieresis",
    "Egrave",
    "Iacute",
    "Icircumflex",
    "Idieresis",
    "Igrave",
    "Ntilde",
    "Oacute",
    "Ocircumflex",
    "Odieresis",
    "Ograve",
    "Otilde",
    "Scaron",
    "Uacute",
    "Ucircumflex",
    "Udieresis",
    "Ugrave",
    "Yacute",
    "Ydieresis",
    "Zcaron",
    "aacute",
    "acircumflex",
    "adieresis",
    "agrave",
    "aring",
    "atilde",
    "ccedilla",
    "eacute",
    "ecircumflex",
    "edieresis",
    "egrave",
    "iacute",
    "icircumflex",
    "idieresis",
    "igrave",
    "ntilde",
    "oacute",
    "ocircumflex",
    "odieresis",
    "ograve",
    "otilde",
    "scaron",
    "uacute",
    "ucircumflex",
    "udieresis",
    "ugrave",
    "yacute",
    "ydieresis",
    "zcaron",
    "exclamsmall",
    "Hungarumlautsmall",
    "dollaroldstyle",
    "dollarsuperior",
    "ampersandsmall",
    "Acutesmall",
    "parenleftsuperior",
    "parenrightsuperior",
    "266 ff",
    "onedotenleader",
    "zerooldstyle",
    "oneoldstyle",
    "twooldstyle",
    "threeoldstyle",
    "fouroldstyle",
    "fiveoldstyle",
    "sixoldstyle",
    "sevenoldstyle",
    "eightoldstyle",
    "nineoldstyle",
    "commasuperior",
    "threequartersemdash",
    "periodsuperior",
    "questionsmall",
    "asuperior",
    "bsuperior",
    "centsuperior",
    "dsuperior",
    "esuperior",
    "isuperior",
    "lsuperior",
    "msuperior",
    "nsuperior",
    "osuperior",
    "rsuperior",
    "ssuperior",
    "tsuperior",
    "ff",
    "ffi",
    "ffl",
    "parenleftinferior",
    "parenrightinferior",
    "Circumflexsmall",
    "hyphensuperior",
    "Gravesmall",
    "Asmall",
    "Bsmall",
    "Csmall",
    "Dsmall",
    "Esmall",
    "Fsmall",
    "Gsmall",
    "Hsmall",
    "Ismall",
    "Jsmall",
    "Ksmall",
    "Lsmall",
    "Msmall",
    "Nsmall",
    "Osmall",
    "Psmall",
    "Qsmall",
    "Rsmall",
    "Ssmall",
    "Tsmall",
    "Usmall",
    "Vsmall",
    "Wsmall",
    "Xsmall",
    "Ysmall",
    "Zsmall",
    "colonmonetary",
    "onefitted",
    "rupiah",
    "Tildesmall",
    "exclamdownsmall",
    "centoldstyle",
    "Lslashsmall",
    "Scaronsmall",
    "Zcaronsmall",
    "Dieresissmall",
    "Brevesmall",
    "Caronsmall",
    "Dotaccentsmall",
    "Macronsmall",
    "figuredash",
    "hypheninferior",
    "Ogoneksmall",
    "Ringsmall",
    "Cedillasmall",
    "questiondownsmall",
    "oneeighth",
    "threeeighths",
    "fiveeighths",
    "seveneighths",
    "onethird",
    "twothirds",
    "zerosuperior",
    "foursuperior",
    "fivesuperior",
    "sixsuperior",
    "sevensuperior",
    "eightsuperior",
    "ninesuperior",
    "zeroinferior",
    "oneinferior",
    "twoinferior",
    "threeinferior",
    "fourinferior",
    "fiveinferior",
    "sixinferior",
    "seveninferior",
    "eightinferior",
    "nineinferior",
    "centinferior",
    "dollarinferior",
    "periodinferior",
    "commainferior",
    "Agravesmall",
    "Aacutesmall",
    "Acircumflexsmall",
    "Atildesmall",
    "Adieresissmall",
    "Aringsmall",
    "AEsmall",
    "Ccedillasmall",
    "Egravesmall",
    "Eacutesmall",
    "Ecircumflexsmall",
    "Edieresissmall",
    "Igravesmall",
    "Iacutesmall",
    "Icircumflexsmall",
    "Idieresissmall",
    "Ethsmall",
    "Ntildesmall",
    "Ogravesmall",
    "Oacutesmall",
    "Ocircumflexsmall",
    "Otildesmall",
    "Odieresissmall",
    "OEsmall",
    "Oslashsmall",
    "Ugravesmall",
    "Uacutesmall",
    "Ucircumflexsmall",
    "Udieresissmall",
    "Yacutesmall",
    "Thornsmall",
    "Ydieresissmall",
    "001.000",
    "001.001",
    "001.002",
    "001.003",
    "Black",
    "Bold",
    "Book",
    "Light",
    "Medium",
    "Regular",
    "Roman",
    "Semibold"
  ];
  var cffStandardEncoding = [
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "space",
    "exclam",
    "quotedbl",
    "numbersign",
    "dollar",
    "percent",
    "ampersand",
    "quoteright",
    "parenleft",
    "parenright",
    "asterisk",
    "plus",
    "comma",
    "hyphen",
    "period",
    "slash",
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "colon",
    "semicolon",
    "less",
    "equal",
    "greater",
    "question",
    "at",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    "bracketleft",
    "backslash",
    "bracketright",
    "asciicircum",
    "underscore",
    "quoteleft",
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "s",
    "t",
    "u",
    "v",
    "w",
    "x",
    "y",
    "z",
    "braceleft",
    "bar",
    "braceright",
    "asciitilde",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "exclamdown",
    "cent",
    "sterling",
    "fraction",
    "yen",
    "florin",
    "section",
    "currency",
    "quotesingle",
    "quotedblleft",
    "guillemotleft",
    "guilsinglleft",
    "guilsinglright",
    "fi",
    "fl",
    "",
    "endash",
    "dagger",
    "daggerdbl",
    "periodcentered",
    "",
    "paragraph",
    "bullet",
    "quotesinglbase",
    "quotedblbase",
    "quotedblright",
    "guillemotright",
    "ellipsis",
    "perthousand",
    "",
    "questiondown",
    "",
    "grave",
    "acute",
    "circumflex",
    "tilde",
    "macron",
    "breve",
    "dotaccent",
    "dieresis",
    "",
    "ring",
    "cedilla",
    "",
    "hungarumlaut",
    "ogonek",
    "caron",
    "emdash",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "AE",
    "",
    "ordfeminine",
    "",
    "",
    "",
    "",
    "Lslash",
    "Oslash",
    "OE",
    "ordmasculine",
    "",
    "",
    "",
    "",
    "",
    "ae",
    "",
    "",
    "",
    "dotlessi",
    "",
    "",
    "lslash",
    "oslash",
    "oe",
    "germandbls"
  ];
  var cffExpertEncoding = [
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "space",
    "exclamsmall",
    "Hungarumlautsmall",
    "",
    "dollaroldstyle",
    "dollarsuperior",
    "ampersandsmall",
    "Acutesmall",
    "parenleftsuperior",
    "parenrightsuperior",
    "twodotenleader",
    "onedotenleader",
    "comma",
    "hyphen",
    "period",
    "fraction",
    "zerooldstyle",
    "oneoldstyle",
    "twooldstyle",
    "threeoldstyle",
    "fouroldstyle",
    "fiveoldstyle",
    "sixoldstyle",
    "sevenoldstyle",
    "eightoldstyle",
    "nineoldstyle",
    "colon",
    "semicolon",
    "commasuperior",
    "threequartersemdash",
    "periodsuperior",
    "questionsmall",
    "",
    "asuperior",
    "bsuperior",
    "centsuperior",
    "dsuperior",
    "esuperior",
    "",
    "",
    "isuperior",
    "",
    "",
    "lsuperior",
    "msuperior",
    "nsuperior",
    "osuperior",
    "",
    "",
    "rsuperior",
    "ssuperior",
    "tsuperior",
    "",
    "ff",
    "fi",
    "fl",
    "ffi",
    "ffl",
    "parenleftinferior",
    "",
    "parenrightinferior",
    "Circumflexsmall",
    "hyphensuperior",
    "Gravesmall",
    "Asmall",
    "Bsmall",
    "Csmall",
    "Dsmall",
    "Esmall",
    "Fsmall",
    "Gsmall",
    "Hsmall",
    "Ismall",
    "Jsmall",
    "Ksmall",
    "Lsmall",
    "Msmall",
    "Nsmall",
    "Osmall",
    "Psmall",
    "Qsmall",
    "Rsmall",
    "Ssmall",
    "Tsmall",
    "Usmall",
    "Vsmall",
    "Wsmall",
    "Xsmall",
    "Ysmall",
    "Zsmall",
    "colonmonetary",
    "onefitted",
    "rupiah",
    "Tildesmall",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "exclamdownsmall",
    "centoldstyle",
    "Lslashsmall",
    "",
    "",
    "Scaronsmall",
    "Zcaronsmall",
    "Dieresissmall",
    "Brevesmall",
    "Caronsmall",
    "",
    "Dotaccentsmall",
    "",
    "",
    "Macronsmall",
    "",
    "",
    "figuredash",
    "hypheninferior",
    "",
    "",
    "Ogoneksmall",
    "Ringsmall",
    "Cedillasmall",
    "",
    "",
    "",
    "onequarter",
    "onehalf",
    "threequarters",
    "questiondownsmall",
    "oneeighth",
    "threeeighths",
    "fiveeighths",
    "seveneighths",
    "onethird",
    "twothirds",
    "",
    "",
    "zerosuperior",
    "onesuperior",
    "twosuperior",
    "threesuperior",
    "foursuperior",
    "fivesuperior",
    "sixsuperior",
    "sevensuperior",
    "eightsuperior",
    "ninesuperior",
    "zeroinferior",
    "oneinferior",
    "twoinferior",
    "threeinferior",
    "fourinferior",
    "fiveinferior",
    "sixinferior",
    "seveninferior",
    "eightinferior",
    "nineinferior",
    "centinferior",
    "dollarinferior",
    "periodinferior",
    "commainferior",
    "Agravesmall",
    "Aacutesmall",
    "Acircumflexsmall",
    "Atildesmall",
    "Adieresissmall",
    "Aringsmall",
    "AEsmall",
    "Ccedillasmall",
    "Egravesmall",
    "Eacutesmall",
    "Ecircumflexsmall",
    "Edieresissmall",
    "Igravesmall",
    "Iacutesmall",
    "Icircumflexsmall",
    "Idieresissmall",
    "Ethsmall",
    "Ntildesmall",
    "Ogravesmall",
    "Oacutesmall",
    "Ocircumflexsmall",
    "Otildesmall",
    "Odieresissmall",
    "OEsmall",
    "Oslashsmall",
    "Ugravesmall",
    "Uacutesmall",
    "Ucircumflexsmall",
    "Udieresissmall",
    "Yacutesmall",
    "Thornsmall",
    "Ydieresissmall"
  ];
  var standardNames = [
    ".notdef",
    ".null",
    "nonmarkingreturn",
    "space",
    "exclam",
    "quotedbl",
    "numbersign",
    "dollar",
    "percent",
    "ampersand",
    "quotesingle",
    "parenleft",
    "parenright",
    "asterisk",
    "plus",
    "comma",
    "hyphen",
    "period",
    "slash",
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "colon",
    "semicolon",
    "less",
    "equal",
    "greater",
    "question",
    "at",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    "bracketleft",
    "backslash",
    "bracketright",
    "asciicircum",
    "underscore",
    "grave",
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "s",
    "t",
    "u",
    "v",
    "w",
    "x",
    "y",
    "z",
    "braceleft",
    "bar",
    "braceright",
    "asciitilde",
    "Adieresis",
    "Aring",
    "Ccedilla",
    "Eacute",
    "Ntilde",
    "Odieresis",
    "Udieresis",
    "aacute",
    "agrave",
    "acircumflex",
    "adieresis",
    "atilde",
    "aring",
    "ccedilla",
    "eacute",
    "egrave",
    "ecircumflex",
    "edieresis",
    "iacute",
    "igrave",
    "icircumflex",
    "idieresis",
    "ntilde",
    "oacute",
    "ograve",
    "ocircumflex",
    "odieresis",
    "otilde",
    "uacute",
    "ugrave",
    "ucircumflex",
    "udieresis",
    "dagger",
    "degree",
    "cent",
    "sterling",
    "section",
    "bullet",
    "paragraph",
    "germandbls",
    "registered",
    "copyright",
    "trademark",
    "acute",
    "dieresis",
    "notequal",
    "AE",
    "Oslash",
    "infinity",
    "plusminus",
    "lessequal",
    "greaterequal",
    "yen",
    "mu",
    "partialdiff",
    "summation",
    "product",
    "pi",
    "integral",
    "ordfeminine",
    "ordmasculine",
    "Omega",
    "ae",
    "oslash",
    "questiondown",
    "exclamdown",
    "logicalnot",
    "radical",
    "florin",
    "approxequal",
    "Delta",
    "guillemotleft",
    "guillemotright",
    "ellipsis",
    "nonbreakingspace",
    "Agrave",
    "Atilde",
    "Otilde",
    "OE",
    "oe",
    "endash",
    "emdash",
    "quotedblleft",
    "quotedblright",
    "quoteleft",
    "quoteright",
    "divide",
    "lozenge",
    "ydieresis",
    "Ydieresis",
    "fraction",
    "currency",
    "guilsinglleft",
    "guilsinglright",
    "fi",
    "fl",
    "daggerdbl",
    "periodcentered",
    "quotesinglbase",
    "quotedblbase",
    "perthousand",
    "Acircumflex",
    "Ecircumflex",
    "Aacute",
    "Edieresis",
    "Egrave",
    "Iacute",
    "Icircumflex",
    "Idieresis",
    "Igrave",
    "Oacute",
    "Ocircumflex",
    "apple",
    "Ograve",
    "Uacute",
    "Ucircumflex",
    "Ugrave",
    "dotlessi",
    "circumflex",
    "tilde",
    "macron",
    "breve",
    "dotaccent",
    "ring",
    "cedilla",
    "hungarumlaut",
    "ogonek",
    "caron",
    "Lslash",
    "lslash",
    "Scaron",
    "scaron",
    "Zcaron",
    "zcaron",
    "brokenbar",
    "Eth",
    "eth",
    "Yacute",
    "yacute",
    "Thorn",
    "thorn",
    "minus",
    "multiply",
    "onesuperior",
    "twosuperior",
    "threesuperior",
    "onehalf",
    "onequarter",
    "threequarters",
    "franc",
    "Gbreve",
    "gbreve",
    "Idotaccent",
    "Scedilla",
    "scedilla",
    "Cacute",
    "cacute",
    "Ccaron",
    "ccaron",
    "dcroat"
  ];
  function DefaultEncoding(font) {
    this.font = font;
  }
  DefaultEncoding.prototype.charToGlyphIndex = function(c) {
    var code = c.codePointAt(0);
    var glyphs = this.font.glyphs;
    if (glyphs) {
      for (var i = 0; i < glyphs.length; i += 1) {
        var glyph = glyphs.get(i);
        for (var j = 0; j < glyph.unicodes.length; j += 1) {
          if (glyph.unicodes[j] === code) {
            return i;
          }
        }
      }
    }
    return null;
  };
  function CmapEncoding(cmap2) {
    this.cmap = cmap2;
  }
  CmapEncoding.prototype.charToGlyphIndex = function(c) {
    return this.cmap.glyphIndexMap[c.codePointAt(0)] || 0;
  };
  function CffEncoding(encoding, charset) {
    this.encoding = encoding;
    this.charset = charset;
  }
  CffEncoding.prototype.charToGlyphIndex = function(s) {
    var code = s.codePointAt(0);
    var charName = this.encoding[code];
    return this.charset.indexOf(charName);
  };
  function GlyphNames(post2) {
    switch (post2.version) {
      case 1:
        this.names = standardNames.slice();
        break;
      case 2:
        this.names = new Array(post2.numberOfGlyphs);
        for (var i = 0; i < post2.numberOfGlyphs; i++) {
          if (post2.glyphNameIndex[i] < standardNames.length) {
            this.names[i] = standardNames[post2.glyphNameIndex[i]];
          } else {
            this.names[i] = post2.names[post2.glyphNameIndex[i] - standardNames.length];
          }
        }
        break;
      case 2.5:
        this.names = new Array(post2.numberOfGlyphs);
        for (var i$1 = 0; i$1 < post2.numberOfGlyphs; i$1++) {
          this.names[i$1] = standardNames[i$1 + post2.glyphNameIndex[i$1]];
        }
        break;
      case 3:
        this.names = [];
        break;
      default:
        this.names = [];
        break;
    }
  }
  GlyphNames.prototype.nameToGlyphIndex = function(name) {
    return this.names.indexOf(name);
  };
  GlyphNames.prototype.glyphIndexToName = function(gid) {
    return this.names[gid];
  };
  function addGlyphNamesAll(font) {
    var glyph;
    var glyphIndexMap = font.tables.cmap.glyphIndexMap;
    var charCodes = Object.keys(glyphIndexMap);
    for (var i = 0; i < charCodes.length; i += 1) {
      var c = charCodes[i];
      var glyphIndex = glyphIndexMap[c];
      glyph = font.glyphs.get(glyphIndex);
      glyph.addUnicode(parseInt(c));
    }
    for (var i$1 = 0; i$1 < font.glyphs.length; i$1 += 1) {
      glyph = font.glyphs.get(i$1);
      if (font.cffEncoding) {
        if (font.isCIDFont) {
          glyph.name = "gid" + i$1;
        } else {
          glyph.name = font.cffEncoding.charset[i$1];
        }
      } else if (font.glyphNames.names) {
        glyph.name = font.glyphNames.glyphIndexToName(i$1);
      }
    }
  }
  function addGlyphNamesToUnicodeMap(font) {
    font._IndexToUnicodeMap = {};
    var glyphIndexMap = font.tables.cmap.glyphIndexMap;
    var charCodes = Object.keys(glyphIndexMap);
    for (var i = 0; i < charCodes.length; i += 1) {
      var c = charCodes[i];
      var glyphIndex = glyphIndexMap[c];
      if (font._IndexToUnicodeMap[glyphIndex] === void 0) {
        font._IndexToUnicodeMap[glyphIndex] = {
          unicodes: [parseInt(c)]
        };
      } else {
        font._IndexToUnicodeMap[glyphIndex].unicodes.push(parseInt(c));
      }
    }
  }
  function addGlyphNames(font, opt) {
    if (opt.lowMemory) {
      addGlyphNamesToUnicodeMap(font);
    } else {
      addGlyphNamesAll(font);
    }
  }
  function line(ctx, x1, y1, x2, y2) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }
  var draw = { line };
  function getPathDefinition(glyph, path2) {
    var _path = path2 || new Path();
    return {
      configurable: true,
      get: function() {
        if (typeof _path === "function") {
          _path = _path();
        }
        return _path;
      },
      set: function(p) {
        _path = p;
      }
    };
  }
  function Glyph(options) {
    this.bindConstructorValues(options);
  }
  Glyph.prototype.bindConstructorValues = function(options) {
    this.index = options.index || 0;
    this.name = options.name || null;
    this.unicode = options.unicode || void 0;
    this.unicodes = options.unicodes || options.unicode !== void 0 ? [options.unicode] : [];
    if ("xMin" in options) {
      this.xMin = options.xMin;
    }
    if ("yMin" in options) {
      this.yMin = options.yMin;
    }
    if ("xMax" in options) {
      this.xMax = options.xMax;
    }
    if ("yMax" in options) {
      this.yMax = options.yMax;
    }
    if ("advanceWidth" in options) {
      this.advanceWidth = options.advanceWidth;
    }
    Object.defineProperty(this, "path", getPathDefinition(this, options.path));
  };
  Glyph.prototype.addUnicode = function(unicode) {
    if (this.unicodes.length === 0) {
      this.unicode = unicode;
    }
    this.unicodes.push(unicode);
  };
  Glyph.prototype.getBoundingBox = function() {
    return this.path.getBoundingBox();
  };
  Glyph.prototype.getPath = function(x, y, fontSize, options, font) {
    x = x !== void 0 ? x : 0;
    y = y !== void 0 ? y : 0;
    fontSize = fontSize !== void 0 ? fontSize : 72;
    var commands;
    var hPoints;
    if (!options) {
      options = {};
    }
    var xScale = options.xScale;
    var yScale = options.yScale;
    if (options.hinting && font && font.hinting) {
      hPoints = this.path && font.hinting.exec(this, fontSize);
    }
    if (hPoints) {
      commands = font.hinting.getCommands(hPoints);
      x = Math.round(x);
      y = Math.round(y);
      xScale = yScale = 1;
    } else {
      commands = this.path.commands;
      var scale = 1 / (this.path.unitsPerEm || 1e3) * fontSize;
      if (xScale === void 0) {
        xScale = scale;
      }
      if (yScale === void 0) {
        yScale = scale;
      }
    }
    var p = new Path();
    for (var i = 0; i < commands.length; i += 1) {
      var cmd = commands[i];
      if (cmd.type === "M") {
        p.moveTo(x + cmd.x * xScale, y + -cmd.y * yScale);
      } else if (cmd.type === "L") {
        p.lineTo(x + cmd.x * xScale, y + -cmd.y * yScale);
      } else if (cmd.type === "Q") {
        p.quadraticCurveTo(
          x + cmd.x1 * xScale,
          y + -cmd.y1 * yScale,
          x + cmd.x * xScale,
          y + -cmd.y * yScale
        );
      } else if (cmd.type === "C") {
        p.curveTo(
          x + cmd.x1 * xScale,
          y + -cmd.y1 * yScale,
          x + cmd.x2 * xScale,
          y + -cmd.y2 * yScale,
          x + cmd.x * xScale,
          y + -cmd.y * yScale
        );
      } else if (cmd.type === "Z") {
        p.closePath();
      }
    }
    return p;
  };
  Glyph.prototype.getContours = function() {
    if (this.points === void 0) {
      return [];
    }
    var contours = [];
    var currentContour = [];
    for (var i = 0; i < this.points.length; i += 1) {
      var pt = this.points[i];
      currentContour.push(pt);
      if (pt.lastPointOfContour) {
        contours.push(currentContour);
        currentContour = [];
      }
    }
    check.argument(currentContour.length === 0, "There are still points left in the current contour.");
    return contours;
  };
  Glyph.prototype.getMetrics = function() {
    var commands = this.path.commands;
    var xCoords = [];
    var yCoords = [];
    for (var i = 0; i < commands.length; i += 1) {
      var cmd = commands[i];
      if (cmd.type !== "Z") {
        xCoords.push(cmd.x);
        yCoords.push(cmd.y);
      }
      if (cmd.type === "Q" || cmd.type === "C") {
        xCoords.push(cmd.x1);
        yCoords.push(cmd.y1);
      }
      if (cmd.type === "C") {
        xCoords.push(cmd.x2);
        yCoords.push(cmd.y2);
      }
    }
    var metrics = {
      xMin: Math.min.apply(null, xCoords),
      yMin: Math.min.apply(null, yCoords),
      xMax: Math.max.apply(null, xCoords),
      yMax: Math.max.apply(null, yCoords),
      leftSideBearing: this.leftSideBearing
    };
    if (!isFinite(metrics.xMin)) {
      metrics.xMin = 0;
    }
    if (!isFinite(metrics.xMax)) {
      metrics.xMax = this.advanceWidth;
    }
    if (!isFinite(metrics.yMin)) {
      metrics.yMin = 0;
    }
    if (!isFinite(metrics.yMax)) {
      metrics.yMax = 0;
    }
    metrics.rightSideBearing = this.advanceWidth - metrics.leftSideBearing - (metrics.xMax - metrics.xMin);
    return metrics;
  };
  Glyph.prototype.draw = function(ctx, x, y, fontSize, options) {
    this.getPath(x, y, fontSize, options).draw(ctx);
  };
  Glyph.prototype.drawPoints = function(ctx, x, y, fontSize) {
    function drawCircles(l, x2, y2, scale2) {
      ctx.beginPath();
      for (var j = 0; j < l.length; j += 1) {
        ctx.moveTo(x2 + l[j].x * scale2, y2 + l[j].y * scale2);
        ctx.arc(x2 + l[j].x * scale2, y2 + l[j].y * scale2, 2, 0, Math.PI * 2, false);
      }
      ctx.closePath();
      ctx.fill();
    }
    x = x !== void 0 ? x : 0;
    y = y !== void 0 ? y : 0;
    fontSize = fontSize !== void 0 ? fontSize : 24;
    var scale = 1 / this.path.unitsPerEm * fontSize;
    var blueCircles = [];
    var redCircles = [];
    var path2 = this.path;
    for (var i = 0; i < path2.commands.length; i += 1) {
      var cmd = path2.commands[i];
      if (cmd.x !== void 0) {
        blueCircles.push({ x: cmd.x, y: -cmd.y });
      }
      if (cmd.x1 !== void 0) {
        redCircles.push({ x: cmd.x1, y: -cmd.y1 });
      }
      if (cmd.x2 !== void 0) {
        redCircles.push({ x: cmd.x2, y: -cmd.y2 });
      }
    }
    ctx.fillStyle = "blue";
    drawCircles(blueCircles, x, y, scale);
    ctx.fillStyle = "red";
    drawCircles(redCircles, x, y, scale);
  };
  Glyph.prototype.drawMetrics = function(ctx, x, y, fontSize) {
    var scale;
    x = x !== void 0 ? x : 0;
    y = y !== void 0 ? y : 0;
    fontSize = fontSize !== void 0 ? fontSize : 24;
    scale = 1 / this.path.unitsPerEm * fontSize;
    ctx.lineWidth = 1;
    ctx.strokeStyle = "black";
    draw.line(ctx, x, -1e4, x, 1e4);
    draw.line(ctx, -1e4, y, 1e4, y);
    var xMin = this.xMin || 0;
    var yMin = this.yMin || 0;
    var xMax = this.xMax || 0;
    var yMax = this.yMax || 0;
    var advanceWidth = this.advanceWidth || 0;
    ctx.strokeStyle = "blue";
    draw.line(ctx, x + xMin * scale, -1e4, x + xMin * scale, 1e4);
    draw.line(ctx, x + xMax * scale, -1e4, x + xMax * scale, 1e4);
    draw.line(ctx, -1e4, y + -yMin * scale, 1e4, y + -yMin * scale);
    draw.line(ctx, -1e4, y + -yMax * scale, 1e4, y + -yMax * scale);
    ctx.strokeStyle = "green";
    draw.line(ctx, x + advanceWidth * scale, -1e4, x + advanceWidth * scale, 1e4);
  };
  function defineDependentProperty(glyph, externalName, internalName) {
    Object.defineProperty(glyph, externalName, {
      get: function() {
        glyph.path;
        return glyph[internalName];
      },
      set: function(newValue) {
        glyph[internalName] = newValue;
      },
      enumerable: true,
      configurable: true
    });
  }
  function GlyphSet(font, glyphs) {
    this.font = font;
    this.glyphs = {};
    if (Array.isArray(glyphs)) {
      for (var i = 0; i < glyphs.length; i++) {
        var glyph = glyphs[i];
        glyph.path.unitsPerEm = font.unitsPerEm;
        this.glyphs[i] = glyph;
      }
    }
    this.length = glyphs && glyphs.length || 0;
  }
  GlyphSet.prototype.get = function(index) {
    if (this.glyphs[index] === void 0) {
      this.font._push(index);
      if (typeof this.glyphs[index] === "function") {
        this.glyphs[index] = this.glyphs[index]();
      }
      var glyph = this.glyphs[index];
      var unicodeObj = this.font._IndexToUnicodeMap[index];
      if (unicodeObj) {
        for (var j = 0; j < unicodeObj.unicodes.length; j++) {
          glyph.addUnicode(unicodeObj.unicodes[j]);
        }
      }
      if (this.font.cffEncoding) {
        if (this.font.isCIDFont) {
          glyph.name = "gid" + index;
        } else {
          glyph.name = this.font.cffEncoding.charset[index];
        }
      } else if (this.font.glyphNames.names) {
        glyph.name = this.font.glyphNames.glyphIndexToName(index);
      }
      this.glyphs[index].advanceWidth = this.font._hmtxTableData[index].advanceWidth;
      this.glyphs[index].leftSideBearing = this.font._hmtxTableData[index].leftSideBearing;
    } else {
      if (typeof this.glyphs[index] === "function") {
        this.glyphs[index] = this.glyphs[index]();
      }
    }
    return this.glyphs[index];
  };
  GlyphSet.prototype.push = function(index, loader) {
    this.glyphs[index] = loader;
    this.length++;
  };
  function glyphLoader(font, index) {
    return new Glyph({ index, font });
  }
  function ttfGlyphLoader(font, index, parseGlyph2, data, position, buildPath2) {
    return function() {
      var glyph = new Glyph({ index, font });
      glyph.path = function() {
        parseGlyph2(glyph, data, position);
        var path2 = buildPath2(font.glyphs, glyph);
        path2.unitsPerEm = font.unitsPerEm;
        return path2;
      };
      defineDependentProperty(glyph, "xMin", "_xMin");
      defineDependentProperty(glyph, "xMax", "_xMax");
      defineDependentProperty(glyph, "yMin", "_yMin");
      defineDependentProperty(glyph, "yMax", "_yMax");
      return glyph;
    };
  }
  function cffGlyphLoader(font, index, parseCFFCharstring2, charstring) {
    return function() {
      var glyph = new Glyph({ index, font });
      glyph.path = function() {
        var path2 = parseCFFCharstring2(font, glyph, charstring);
        path2.unitsPerEm = font.unitsPerEm;
        return path2;
      };
      return glyph;
    };
  }
  var glyphset = { GlyphSet, glyphLoader, ttfGlyphLoader, cffGlyphLoader };
  function equals(a, b) {
    if (a === b) {
      return true;
    } else if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) {
        return false;
      }
      for (var i = 0; i < a.length; i += 1) {
        if (!equals(a[i], b[i])) {
          return false;
        }
      }
      return true;
    } else {
      return false;
    }
  }
  function calcCFFSubroutineBias(subrs) {
    var bias;
    if (subrs.length < 1240) {
      bias = 107;
    } else if (subrs.length < 33900) {
      bias = 1131;
    } else {
      bias = 32768;
    }
    return bias;
  }
  function parseCFFIndex(data, start, conversionFn) {
    var offsets = [];
    var objects = [];
    var count = parse.getCard16(data, start);
    var objectOffset;
    var endOffset;
    if (count !== 0) {
      var offsetSize = parse.getByte(data, start + 2);
      objectOffset = start + (count + 1) * offsetSize + 2;
      var pos = start + 3;
      for (var i = 0; i < count + 1; i += 1) {
        offsets.push(parse.getOffset(data, pos, offsetSize));
        pos += offsetSize;
      }
      endOffset = objectOffset + offsets[count];
    } else {
      endOffset = start + 2;
    }
    for (var i$1 = 0; i$1 < offsets.length - 1; i$1 += 1) {
      var value = parse.getBytes(data, objectOffset + offsets[i$1], objectOffset + offsets[i$1 + 1]);
      if (conversionFn) {
        value = conversionFn(value);
      }
      objects.push(value);
    }
    return { objects, startOffset: start, endOffset };
  }
  function parseCFFIndexLowMemory(data, start) {
    var offsets = [];
    var count = parse.getCard16(data, start);
    var objectOffset;
    var endOffset;
    if (count !== 0) {
      var offsetSize = parse.getByte(data, start + 2);
      objectOffset = start + (count + 1) * offsetSize + 2;
      var pos = start + 3;
      for (var i = 0; i < count + 1; i += 1) {
        offsets.push(parse.getOffset(data, pos, offsetSize));
        pos += offsetSize;
      }
      endOffset = objectOffset + offsets[count];
    } else {
      endOffset = start + 2;
    }
    return { offsets, startOffset: start, endOffset };
  }
  function getCffIndexObject(i, offsets, data, start, conversionFn) {
    var count = parse.getCard16(data, start);
    var objectOffset = 0;
    if (count !== 0) {
      var offsetSize = parse.getByte(data, start + 2);
      objectOffset = start + (count + 1) * offsetSize + 2;
    }
    var value = parse.getBytes(data, objectOffset + offsets[i], objectOffset + offsets[i + 1]);
    if (conversionFn) {
      value = conversionFn(value);
    }
    return value;
  }
  function parseFloatOperand(parser) {
    var s = "";
    var eof = 15;
    var lookup = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "E", "E-", null, "-"];
    while (true) {
      var b = parser.parseByte();
      var n1 = b >> 4;
      var n2 = b & 15;
      if (n1 === eof) {
        break;
      }
      s += lookup[n1];
      if (n2 === eof) {
        break;
      }
      s += lookup[n2];
    }
    return parseFloat(s);
  }
  function parseOperand(parser, b0) {
    var b1;
    var b2;
    var b3;
    var b4;
    if (b0 === 28) {
      b1 = parser.parseByte();
      b2 = parser.parseByte();
      return b1 << 8 | b2;
    }
    if (b0 === 29) {
      b1 = parser.parseByte();
      b2 = parser.parseByte();
      b3 = parser.parseByte();
      b4 = parser.parseByte();
      return b1 << 24 | b2 << 16 | b3 << 8 | b4;
    }
    if (b0 === 30) {
      return parseFloatOperand(parser);
    }
    if (b0 >= 32 && b0 <= 246) {
      return b0 - 139;
    }
    if (b0 >= 247 && b0 <= 250) {
      b1 = parser.parseByte();
      return (b0 - 247) * 256 + b1 + 108;
    }
    if (b0 >= 251 && b0 <= 254) {
      b1 = parser.parseByte();
      return -(b0 - 251) * 256 - b1 - 108;
    }
    throw new Error("Invalid b0 " + b0);
  }
  function entriesToObject(entries) {
    var o = {};
    for (var i = 0; i < entries.length; i += 1) {
      var key = entries[i][0];
      var values = entries[i][1];
      var value = void 0;
      if (values.length === 1) {
        value = values[0];
      } else {
        value = values;
      }
      if (o.hasOwnProperty(key) && !isNaN(o[key])) {
        throw new Error("Object " + o + " already has key " + key);
      }
      o[key] = value;
    }
    return o;
  }
  function parseCFFDict(data, start, size) {
    start = start !== void 0 ? start : 0;
    var parser = new parse.Parser(data, start);
    var entries = [];
    var operands = [];
    size = size !== void 0 ? size : data.length;
    while (parser.relativeOffset < size) {
      var op = parser.parseByte();
      if (op <= 21) {
        if (op === 12) {
          op = 1200 + parser.parseByte();
        }
        entries.push([op, operands]);
        operands = [];
      } else {
        operands.push(parseOperand(parser, op));
      }
    }
    return entriesToObject(entries);
  }
  function getCFFString(strings, index) {
    if (index <= 390) {
      index = cffStandardStrings[index];
    } else {
      index = strings[index - 391];
    }
    return index;
  }
  function interpretDict(dict, meta2, strings) {
    var newDict = {};
    var value;
    for (var i = 0; i < meta2.length; i += 1) {
      var m = meta2[i];
      if (Array.isArray(m.type)) {
        var values = [];
        values.length = m.type.length;
        for (var j = 0; j < m.type.length; j++) {
          value = dict[m.op] !== void 0 ? dict[m.op][j] : void 0;
          if (value === void 0) {
            value = m.value !== void 0 && m.value[j] !== void 0 ? m.value[j] : null;
          }
          if (m.type[j] === "SID") {
            value = getCFFString(strings, value);
          }
          values[j] = value;
        }
        newDict[m.name] = values;
      } else {
        value = dict[m.op];
        if (value === void 0) {
          value = m.value !== void 0 ? m.value : null;
        }
        if (m.type === "SID") {
          value = getCFFString(strings, value);
        }
        newDict[m.name] = value;
      }
    }
    return newDict;
  }
  function parseCFFHeader(data, start) {
    var header = {};
    header.formatMajor = parse.getCard8(data, start);
    header.formatMinor = parse.getCard8(data, start + 1);
    header.size = parse.getCard8(data, start + 2);
    header.offsetSize = parse.getCard8(data, start + 3);
    header.startOffset = start;
    header.endOffset = start + 4;
    return header;
  }
  var TOP_DICT_META = [
    { name: "version", op: 0, type: "SID" },
    { name: "notice", op: 1, type: "SID" },
    { name: "copyright", op: 1200, type: "SID" },
    { name: "fullName", op: 2, type: "SID" },
    { name: "familyName", op: 3, type: "SID" },
    { name: "weight", op: 4, type: "SID" },
    { name: "isFixedPitch", op: 1201, type: "number", value: 0 },
    { name: "italicAngle", op: 1202, type: "number", value: 0 },
    { name: "underlinePosition", op: 1203, type: "number", value: -100 },
    { name: "underlineThickness", op: 1204, type: "number", value: 50 },
    { name: "paintType", op: 1205, type: "number", value: 0 },
    { name: "charstringType", op: 1206, type: "number", value: 2 },
    {
      name: "fontMatrix",
      op: 1207,
      type: ["real", "real", "real", "real", "real", "real"],
      value: [1e-3, 0, 0, 1e-3, 0, 0]
    },
    { name: "uniqueId", op: 13, type: "number" },
    { name: "fontBBox", op: 5, type: ["number", "number", "number", "number"], value: [0, 0, 0, 0] },
    { name: "strokeWidth", op: 1208, type: "number", value: 0 },
    { name: "xuid", op: 14, type: [], value: null },
    { name: "charset", op: 15, type: "offset", value: 0 },
    { name: "encoding", op: 16, type: "offset", value: 0 },
    { name: "charStrings", op: 17, type: "offset", value: 0 },
    { name: "private", op: 18, type: ["number", "offset"], value: [0, 0] },
    { name: "ros", op: 1230, type: ["SID", "SID", "number"] },
    { name: "cidFontVersion", op: 1231, type: "number", value: 0 },
    { name: "cidFontRevision", op: 1232, type: "number", value: 0 },
    { name: "cidFontType", op: 1233, type: "number", value: 0 },
    { name: "cidCount", op: 1234, type: "number", value: 8720 },
    { name: "uidBase", op: 1235, type: "number" },
    { name: "fdArray", op: 1236, type: "offset" },
    { name: "fdSelect", op: 1237, type: "offset" },
    { name: "fontName", op: 1238, type: "SID" }
  ];
  var PRIVATE_DICT_META = [
    { name: "subrs", op: 19, type: "offset", value: 0 },
    { name: "defaultWidthX", op: 20, type: "number", value: 0 },
    { name: "nominalWidthX", op: 21, type: "number", value: 0 }
  ];
  function parseCFFTopDict(data, strings) {
    var dict = parseCFFDict(data, 0, data.byteLength);
    return interpretDict(dict, TOP_DICT_META, strings);
  }
  function parseCFFPrivateDict(data, start, size, strings) {
    var dict = parseCFFDict(data, start, size);
    return interpretDict(dict, PRIVATE_DICT_META, strings);
  }
  function gatherCFFTopDicts(data, start, cffIndex, strings) {
    var topDictArray = [];
    for (var iTopDict = 0; iTopDict < cffIndex.length; iTopDict += 1) {
      var topDictData = new DataView(new Uint8Array(cffIndex[iTopDict]).buffer);
      var topDict = parseCFFTopDict(topDictData, strings);
      topDict._subrs = [];
      topDict._subrsBias = 0;
      topDict._defaultWidthX = 0;
      topDict._nominalWidthX = 0;
      var privateSize = topDict.private[0];
      var privateOffset = topDict.private[1];
      if (privateSize !== 0 && privateOffset !== 0) {
        var privateDict = parseCFFPrivateDict(data, privateOffset + start, privateSize, strings);
        topDict._defaultWidthX = privateDict.defaultWidthX;
        topDict._nominalWidthX = privateDict.nominalWidthX;
        if (privateDict.subrs !== 0) {
          var subrOffset = privateOffset + privateDict.subrs;
          var subrIndex = parseCFFIndex(data, subrOffset + start);
          topDict._subrs = subrIndex.objects;
          topDict._subrsBias = calcCFFSubroutineBias(topDict._subrs);
        }
        topDict._privateDict = privateDict;
      }
      topDictArray.push(topDict);
    }
    return topDictArray;
  }
  function parseCFFCharset(data, start, nGlyphs, strings) {
    var sid;
    var count;
    var parser = new parse.Parser(data, start);
    nGlyphs -= 1;
    var charset = [".notdef"];
    var format = parser.parseCard8();
    if (format === 0) {
      for (var i = 0; i < nGlyphs; i += 1) {
        sid = parser.parseSID();
        charset.push(getCFFString(strings, sid));
      }
    } else if (format === 1) {
      while (charset.length <= nGlyphs) {
        sid = parser.parseSID();
        count = parser.parseCard8();
        for (var i$1 = 0; i$1 <= count; i$1 += 1) {
          charset.push(getCFFString(strings, sid));
          sid += 1;
        }
      }
    } else if (format === 2) {
      while (charset.length <= nGlyphs) {
        sid = parser.parseSID();
        count = parser.parseCard16();
        for (var i$2 = 0; i$2 <= count; i$2 += 1) {
          charset.push(getCFFString(strings, sid));
          sid += 1;
        }
      }
    } else {
      throw new Error("Unknown charset format " + format);
    }
    return charset;
  }
  function parseCFFEncoding(data, start, charset) {
    var code;
    var enc = {};
    var parser = new parse.Parser(data, start);
    var format = parser.parseCard8();
    if (format === 0) {
      var nCodes = parser.parseCard8();
      for (var i = 0; i < nCodes; i += 1) {
        code = parser.parseCard8();
        enc[code] = i;
      }
    } else if (format === 1) {
      var nRanges = parser.parseCard8();
      code = 1;
      for (var i$1 = 0; i$1 < nRanges; i$1 += 1) {
        var first = parser.parseCard8();
        var nLeft = parser.parseCard8();
        for (var j = first; j <= first + nLeft; j += 1) {
          enc[j] = code;
          code += 1;
        }
      }
    } else {
      throw new Error("Unknown encoding format " + format);
    }
    return new CffEncoding(enc, charset);
  }
  function parseCFFCharstring(font, glyph, code) {
    var c1x;
    var c1y;
    var c2x;
    var c2y;
    var p = new Path();
    var stack = [];
    var nStems = 0;
    var haveWidth = false;
    var open = false;
    var x = 0;
    var y = 0;
    var subrs;
    var subrsBias;
    var defaultWidthX;
    var nominalWidthX;
    if (font.isCIDFont) {
      var fdIndex = font.tables.cff.topDict._fdSelect[glyph.index];
      var fdDict = font.tables.cff.topDict._fdArray[fdIndex];
      subrs = fdDict._subrs;
      subrsBias = fdDict._subrsBias;
      defaultWidthX = fdDict._defaultWidthX;
      nominalWidthX = fdDict._nominalWidthX;
    } else {
      subrs = font.tables.cff.topDict._subrs;
      subrsBias = font.tables.cff.topDict._subrsBias;
      defaultWidthX = font.tables.cff.topDict._defaultWidthX;
      nominalWidthX = font.tables.cff.topDict._nominalWidthX;
    }
    var width = defaultWidthX;
    function newContour(x2, y2) {
      if (open) {
        p.closePath();
      }
      p.moveTo(x2, y2);
      open = true;
    }
    function parseStems() {
      var hasWidthArg;
      hasWidthArg = stack.length % 2 !== 0;
      if (hasWidthArg && !haveWidth) {
        width = stack.shift() + nominalWidthX;
      }
      nStems += stack.length >> 1;
      stack.length = 0;
      haveWidth = true;
    }
    function parse2(code2) {
      var b1;
      var b2;
      var b3;
      var b4;
      var codeIndex;
      var subrCode;
      var jpx;
      var jpy;
      var c3x;
      var c3y;
      var c4x;
      var c4y;
      var i = 0;
      while (i < code2.length) {
        var v = code2[i];
        i += 1;
        switch (v) {
          case 1:
            parseStems();
            break;
          case 3:
            parseStems();
            break;
          case 4:
            if (stack.length > 1 && !haveWidth) {
              width = stack.shift() + nominalWidthX;
              haveWidth = true;
            }
            y += stack.pop();
            newContour(x, y);
            break;
          case 5:
            while (stack.length > 0) {
              x += stack.shift();
              y += stack.shift();
              p.lineTo(x, y);
            }
            break;
          case 6:
            while (stack.length > 0) {
              x += stack.shift();
              p.lineTo(x, y);
              if (stack.length === 0) {
                break;
              }
              y += stack.shift();
              p.lineTo(x, y);
            }
            break;
          case 7:
            while (stack.length > 0) {
              y += stack.shift();
              p.lineTo(x, y);
              if (stack.length === 0) {
                break;
              }
              x += stack.shift();
              p.lineTo(x, y);
            }
            break;
          case 8:
            while (stack.length > 0) {
              c1x = x + stack.shift();
              c1y = y + stack.shift();
              c2x = c1x + stack.shift();
              c2y = c1y + stack.shift();
              x = c2x + stack.shift();
              y = c2y + stack.shift();
              p.curveTo(c1x, c1y, c2x, c2y, x, y);
            }
            break;
          case 10:
            codeIndex = stack.pop() + subrsBias;
            subrCode = subrs[codeIndex];
            if (subrCode) {
              parse2(subrCode);
            }
            break;
          case 11:
            return;
          case 12:
            v = code2[i];
            i += 1;
            switch (v) {
              case 35:
                c1x = x + stack.shift();
                c1y = y + stack.shift();
                c2x = c1x + stack.shift();
                c2y = c1y + stack.shift();
                jpx = c2x + stack.shift();
                jpy = c2y + stack.shift();
                c3x = jpx + stack.shift();
                c3y = jpy + stack.shift();
                c4x = c3x + stack.shift();
                c4y = c3y + stack.shift();
                x = c4x + stack.shift();
                y = c4y + stack.shift();
                stack.shift();
                p.curveTo(c1x, c1y, c2x, c2y, jpx, jpy);
                p.curveTo(c3x, c3y, c4x, c4y, x, y);
                break;
              case 34:
                c1x = x + stack.shift();
                c1y = y;
                c2x = c1x + stack.shift();
                c2y = c1y + stack.shift();
                jpx = c2x + stack.shift();
                jpy = c2y;
                c3x = jpx + stack.shift();
                c3y = c2y;
                c4x = c3x + stack.shift();
                c4y = y;
                x = c4x + stack.shift();
                p.curveTo(c1x, c1y, c2x, c2y, jpx, jpy);
                p.curveTo(c3x, c3y, c4x, c4y, x, y);
                break;
              case 36:
                c1x = x + stack.shift();
                c1y = y + stack.shift();
                c2x = c1x + stack.shift();
                c2y = c1y + stack.shift();
                jpx = c2x + stack.shift();
                jpy = c2y;
                c3x = jpx + stack.shift();
                c3y = c2y;
                c4x = c3x + stack.shift();
                c4y = c3y + stack.shift();
                x = c4x + stack.shift();
                p.curveTo(c1x, c1y, c2x, c2y, jpx, jpy);
                p.curveTo(c3x, c3y, c4x, c4y, x, y);
                break;
              case 37:
                c1x = x + stack.shift();
                c1y = y + stack.shift();
                c2x = c1x + stack.shift();
                c2y = c1y + stack.shift();
                jpx = c2x + stack.shift();
                jpy = c2y + stack.shift();
                c3x = jpx + stack.shift();
                c3y = jpy + stack.shift();
                c4x = c3x + stack.shift();
                c4y = c3y + stack.shift();
                if (Math.abs(c4x - x) > Math.abs(c4y - y)) {
                  x = c4x + stack.shift();
                } else {
                  y = c4y + stack.shift();
                }
                p.curveTo(c1x, c1y, c2x, c2y, jpx, jpy);
                p.curveTo(c3x, c3y, c4x, c4y, x, y);
                break;
              default:
                console.log("Glyph " + glyph.index + ": unknown operator 1200" + v);
                stack.length = 0;
            }
            break;
          case 14:
            if (stack.length > 0 && !haveWidth) {
              width = stack.shift() + nominalWidthX;
              haveWidth = true;
            }
            if (open) {
              p.closePath();
              open = false;
            }
            break;
          case 18:
            parseStems();
            break;
          case 19:
          case 20:
            parseStems();
            i += nStems + 7 >> 3;
            break;
          case 21:
            if (stack.length > 2 && !haveWidth) {
              width = stack.shift() + nominalWidthX;
              haveWidth = true;
            }
            y += stack.pop();
            x += stack.pop();
            newContour(x, y);
            break;
          case 22:
            if (stack.length > 1 && !haveWidth) {
              width = stack.shift() + nominalWidthX;
              haveWidth = true;
            }
            x += stack.pop();
            newContour(x, y);
            break;
          case 23:
            parseStems();
            break;
          case 24:
            while (stack.length > 2) {
              c1x = x + stack.shift();
              c1y = y + stack.shift();
              c2x = c1x + stack.shift();
              c2y = c1y + stack.shift();
              x = c2x + stack.shift();
              y = c2y + stack.shift();
              p.curveTo(c1x, c1y, c2x, c2y, x, y);
            }
            x += stack.shift();
            y += stack.shift();
            p.lineTo(x, y);
            break;
          case 25:
            while (stack.length > 6) {
              x += stack.shift();
              y += stack.shift();
              p.lineTo(x, y);
            }
            c1x = x + stack.shift();
            c1y = y + stack.shift();
            c2x = c1x + stack.shift();
            c2y = c1y + stack.shift();
            x = c2x + stack.shift();
            y = c2y + stack.shift();
            p.curveTo(c1x, c1y, c2x, c2y, x, y);
            break;
          case 26:
            if (stack.length % 2) {
              x += stack.shift();
            }
            while (stack.length > 0) {
              c1x = x;
              c1y = y + stack.shift();
              c2x = c1x + stack.shift();
              c2y = c1y + stack.shift();
              x = c2x;
              y = c2y + stack.shift();
              p.curveTo(c1x, c1y, c2x, c2y, x, y);
            }
            break;
          case 27:
            if (stack.length % 2) {
              y += stack.shift();
            }
            while (stack.length > 0) {
              c1x = x + stack.shift();
              c1y = y;
              c2x = c1x + stack.shift();
              c2y = c1y + stack.shift();
              x = c2x + stack.shift();
              y = c2y;
              p.curveTo(c1x, c1y, c2x, c2y, x, y);
            }
            break;
          case 28:
            b1 = code2[i];
            b2 = code2[i + 1];
            stack.push((b1 << 24 | b2 << 16) >> 16);
            i += 2;
            break;
          case 29:
            codeIndex = stack.pop() + font.gsubrsBias;
            subrCode = font.gsubrs[codeIndex];
            if (subrCode) {
              parse2(subrCode);
            }
            break;
          case 30:
            while (stack.length > 0) {
              c1x = x;
              c1y = y + stack.shift();
              c2x = c1x + stack.shift();
              c2y = c1y + stack.shift();
              x = c2x + stack.shift();
              y = c2y + (stack.length === 1 ? stack.shift() : 0);
              p.curveTo(c1x, c1y, c2x, c2y, x, y);
              if (stack.length === 0) {
                break;
              }
              c1x = x + stack.shift();
              c1y = y;
              c2x = c1x + stack.shift();
              c2y = c1y + stack.shift();
              y = c2y + stack.shift();
              x = c2x + (stack.length === 1 ? stack.shift() : 0);
              p.curveTo(c1x, c1y, c2x, c2y, x, y);
            }
            break;
          case 31:
            while (stack.length > 0) {
              c1x = x + stack.shift();
              c1y = y;
              c2x = c1x + stack.shift();
              c2y = c1y + stack.shift();
              y = c2y + stack.shift();
              x = c2x + (stack.length === 1 ? stack.shift() : 0);
              p.curveTo(c1x, c1y, c2x, c2y, x, y);
              if (stack.length === 0) {
                break;
              }
              c1x = x;
              c1y = y + stack.shift();
              c2x = c1x + stack.shift();
              c2y = c1y + stack.shift();
              x = c2x + stack.shift();
              y = c2y + (stack.length === 1 ? stack.shift() : 0);
              p.curveTo(c1x, c1y, c2x, c2y, x, y);
            }
            break;
          default:
            if (v < 32) {
              console.log("Glyph " + glyph.index + ": unknown operator " + v);
            } else if (v < 247) {
              stack.push(v - 139);
            } else if (v < 251) {
              b1 = code2[i];
              i += 1;
              stack.push((v - 247) * 256 + b1 + 108);
            } else if (v < 255) {
              b1 = code2[i];
              i += 1;
              stack.push(-(v - 251) * 256 - b1 - 108);
            } else {
              b1 = code2[i];
              b2 = code2[i + 1];
              b3 = code2[i + 2];
              b4 = code2[i + 3];
              i += 4;
              stack.push((b1 << 24 | b2 << 16 | b3 << 8 | b4) / 65536);
            }
        }
      }
    }
    parse2(code);
    glyph.advanceWidth = width;
    return p;
  }
  function parseCFFFDSelect(data, start, nGlyphs, fdArrayCount) {
    var fdSelect = [];
    var fdIndex;
    var parser = new parse.Parser(data, start);
    var format = parser.parseCard8();
    if (format === 0) {
      for (var iGid = 0; iGid < nGlyphs; iGid++) {
        fdIndex = parser.parseCard8();
        if (fdIndex >= fdArrayCount) {
          throw new Error("CFF table CID Font FDSelect has bad FD index value " + fdIndex + " (FD count " + fdArrayCount + ")");
        }
        fdSelect.push(fdIndex);
      }
    } else if (format === 3) {
      var nRanges = parser.parseCard16();
      var first = parser.parseCard16();
      if (first !== 0) {
        throw new Error("CFF Table CID Font FDSelect format 3 range has bad initial GID " + first);
      }
      var next;
      for (var iRange = 0; iRange < nRanges; iRange++) {
        fdIndex = parser.parseCard8();
        next = parser.parseCard16();
        if (fdIndex >= fdArrayCount) {
          throw new Error("CFF table CID Font FDSelect has bad FD index value " + fdIndex + " (FD count " + fdArrayCount + ")");
        }
        if (next > nGlyphs) {
          throw new Error("CFF Table CID Font FDSelect format 3 range has bad GID " + next);
        }
        for (; first < next; first++) {
          fdSelect.push(fdIndex);
        }
        first = next;
      }
      if (next !== nGlyphs) {
        throw new Error("CFF Table CID Font FDSelect format 3 range has bad final GID " + next);
      }
    } else {
      throw new Error("CFF Table CID Font FDSelect table has unsupported format " + format);
    }
    return fdSelect;
  }
  function parseCFFTable(data, start, font, opt) {
    font.tables.cff = {};
    var header = parseCFFHeader(data, start);
    var nameIndex = parseCFFIndex(data, header.endOffset, parse.bytesToString);
    var topDictIndex = parseCFFIndex(data, nameIndex.endOffset);
    var stringIndex = parseCFFIndex(data, topDictIndex.endOffset, parse.bytesToString);
    var globalSubrIndex = parseCFFIndex(data, stringIndex.endOffset);
    font.gsubrs = globalSubrIndex.objects;
    font.gsubrsBias = calcCFFSubroutineBias(font.gsubrs);
    var topDictArray = gatherCFFTopDicts(data, start, topDictIndex.objects, stringIndex.objects);
    if (topDictArray.length !== 1) {
      throw new Error("CFF table has too many fonts in 'FontSet' - count of fonts NameIndex.length = " + topDictArray.length);
    }
    var topDict = topDictArray[0];
    font.tables.cff.topDict = topDict;
    if (topDict._privateDict) {
      font.defaultWidthX = topDict._privateDict.defaultWidthX;
      font.nominalWidthX = topDict._privateDict.nominalWidthX;
    }
    if (topDict.ros[0] !== void 0 && topDict.ros[1] !== void 0) {
      font.isCIDFont = true;
    }
    if (font.isCIDFont) {
      var fdArrayOffset = topDict.fdArray;
      var fdSelectOffset = topDict.fdSelect;
      if (fdArrayOffset === 0 || fdSelectOffset === 0) {
        throw new Error("Font is marked as a CID font, but FDArray and/or FDSelect information is missing");
      }
      fdArrayOffset += start;
      var fdArrayIndex = parseCFFIndex(data, fdArrayOffset);
      var fdArray = gatherCFFTopDicts(data, start, fdArrayIndex.objects, stringIndex.objects);
      topDict._fdArray = fdArray;
      fdSelectOffset += start;
      topDict._fdSelect = parseCFFFDSelect(data, fdSelectOffset, font.numGlyphs, fdArray.length);
    }
    var privateDictOffset = start + topDict.private[1];
    var privateDict = parseCFFPrivateDict(data, privateDictOffset, topDict.private[0], stringIndex.objects);
    font.defaultWidthX = privateDict.defaultWidthX;
    font.nominalWidthX = privateDict.nominalWidthX;
    if (privateDict.subrs !== 0) {
      var subrOffset = privateDictOffset + privateDict.subrs;
      var subrIndex = parseCFFIndex(data, subrOffset);
      font.subrs = subrIndex.objects;
      font.subrsBias = calcCFFSubroutineBias(font.subrs);
    } else {
      font.subrs = [];
      font.subrsBias = 0;
    }
    var charStringsIndex;
    if (opt.lowMemory) {
      charStringsIndex = parseCFFIndexLowMemory(data, start + topDict.charStrings);
      font.nGlyphs = charStringsIndex.offsets.length;
    } else {
      charStringsIndex = parseCFFIndex(data, start + topDict.charStrings);
      font.nGlyphs = charStringsIndex.objects.length;
    }
    var charset = parseCFFCharset(data, start + topDict.charset, font.nGlyphs, stringIndex.objects);
    if (topDict.encoding === 0) {
      font.cffEncoding = new CffEncoding(cffStandardEncoding, charset);
    } else if (topDict.encoding === 1) {
      font.cffEncoding = new CffEncoding(cffExpertEncoding, charset);
    } else {
      font.cffEncoding = parseCFFEncoding(data, start + topDict.encoding, charset);
    }
    font.encoding = font.encoding || font.cffEncoding;
    font.glyphs = new glyphset.GlyphSet(font);
    if (opt.lowMemory) {
      font._push = function(i2) {
        var charString2 = getCffIndexObject(i2, charStringsIndex.offsets, data, start + topDict.charStrings);
        font.glyphs.push(i2, glyphset.cffGlyphLoader(font, i2, parseCFFCharstring, charString2));
      };
    } else {
      for (var i = 0; i < font.nGlyphs; i += 1) {
        var charString = charStringsIndex.objects[i];
        font.glyphs.push(i, glyphset.cffGlyphLoader(font, i, parseCFFCharstring, charString));
      }
    }
  }
  function encodeString(s, strings) {
    var sid;
    var i = cffStandardStrings.indexOf(s);
    if (i >= 0) {
      sid = i;
    }
    i = strings.indexOf(s);
    if (i >= 0) {
      sid = i + cffStandardStrings.length;
    } else {
      sid = cffStandardStrings.length + strings.length;
      strings.push(s);
    }
    return sid;
  }
  function makeHeader() {
    return new table.Record("Header", [
      { name: "major", type: "Card8", value: 1 },
      { name: "minor", type: "Card8", value: 0 },
      { name: "hdrSize", type: "Card8", value: 4 },
      { name: "major", type: "Card8", value: 1 }
    ]);
  }
  function makeNameIndex(fontNames) {
    var t = new table.Record("Name INDEX", [
      { name: "names", type: "INDEX", value: [] }
    ]);
    t.names = [];
    for (var i = 0; i < fontNames.length; i += 1) {
      t.names.push({ name: "name_" + i, type: "NAME", value: fontNames[i] });
    }
    return t;
  }
  function makeDict(meta2, attrs, strings) {
    var m = {};
    for (var i = 0; i < meta2.length; i += 1) {
      var entry = meta2[i];
      var value = attrs[entry.name];
      if (value !== void 0 && !equals(value, entry.value)) {
        if (entry.type === "SID") {
          value = encodeString(value, strings);
        }
        m[entry.op] = { name: entry.name, type: entry.type, value };
      }
    }
    return m;
  }
  function makeTopDict(attrs, strings) {
    var t = new table.Record("Top DICT", [
      { name: "dict", type: "DICT", value: {} }
    ]);
    t.dict = makeDict(TOP_DICT_META, attrs, strings);
    return t;
  }
  function makeTopDictIndex(topDict) {
    var t = new table.Record("Top DICT INDEX", [
      { name: "topDicts", type: "INDEX", value: [] }
    ]);
    t.topDicts = [{ name: "topDict_0", type: "TABLE", value: topDict }];
    return t;
  }
  function makeStringIndex(strings) {
    var t = new table.Record("String INDEX", [
      { name: "strings", type: "INDEX", value: [] }
    ]);
    t.strings = [];
    for (var i = 0; i < strings.length; i += 1) {
      t.strings.push({ name: "string_" + i, type: "STRING", value: strings[i] });
    }
    return t;
  }
  function makeGlobalSubrIndex() {
    return new table.Record("Global Subr INDEX", [
      { name: "subrs", type: "INDEX", value: [] }
    ]);
  }
  function makeCharsets(glyphNames, strings) {
    var t = new table.Record("Charsets", [
      { name: "format", type: "Card8", value: 0 }
    ]);
    for (var i = 0; i < glyphNames.length; i += 1) {
      var glyphName = glyphNames[i];
      var glyphSID = encodeString(glyphName, strings);
      t.fields.push({ name: "glyph_" + i, type: "SID", value: glyphSID });
    }
    return t;
  }
  function glyphToOps(glyph) {
    var ops = [];
    var path2 = glyph.path;
    ops.push({ name: "width", type: "NUMBER", value: glyph.advanceWidth });
    var x = 0;
    var y = 0;
    for (var i = 0; i < path2.commands.length; i += 1) {
      var dx = void 0;
      var dy = void 0;
      var cmd = path2.commands[i];
      if (cmd.type === "Q") {
        var _13 = 1 / 3;
        var _23 = 2 / 3;
        cmd = {
          type: "C",
          x: cmd.x,
          y: cmd.y,
          x1: Math.round(_13 * x + _23 * cmd.x1),
          y1: Math.round(_13 * y + _23 * cmd.y1),
          x2: Math.round(_13 * cmd.x + _23 * cmd.x1),
          y2: Math.round(_13 * cmd.y + _23 * cmd.y1)
        };
      }
      if (cmd.type === "M") {
        dx = Math.round(cmd.x - x);
        dy = Math.round(cmd.y - y);
        ops.push({ name: "dx", type: "NUMBER", value: dx });
        ops.push({ name: "dy", type: "NUMBER", value: dy });
        ops.push({ name: "rmoveto", type: "OP", value: 21 });
        x = Math.round(cmd.x);
        y = Math.round(cmd.y);
      } else if (cmd.type === "L") {
        dx = Math.round(cmd.x - x);
        dy = Math.round(cmd.y - y);
        ops.push({ name: "dx", type: "NUMBER", value: dx });
        ops.push({ name: "dy", type: "NUMBER", value: dy });
        ops.push({ name: "rlineto", type: "OP", value: 5 });
        x = Math.round(cmd.x);
        y = Math.round(cmd.y);
      } else if (cmd.type === "C") {
        var dx1 = Math.round(cmd.x1 - x);
        var dy1 = Math.round(cmd.y1 - y);
        var dx2 = Math.round(cmd.x2 - cmd.x1);
        var dy2 = Math.round(cmd.y2 - cmd.y1);
        dx = Math.round(cmd.x - cmd.x2);
        dy = Math.round(cmd.y - cmd.y2);
        ops.push({ name: "dx1", type: "NUMBER", value: dx1 });
        ops.push({ name: "dy1", type: "NUMBER", value: dy1 });
        ops.push({ name: "dx2", type: "NUMBER", value: dx2 });
        ops.push({ name: "dy2", type: "NUMBER", value: dy2 });
        ops.push({ name: "dx", type: "NUMBER", value: dx });
        ops.push({ name: "dy", type: "NUMBER", value: dy });
        ops.push({ name: "rrcurveto", type: "OP", value: 8 });
        x = Math.round(cmd.x);
        y = Math.round(cmd.y);
      }
    }
    ops.push({ name: "endchar", type: "OP", value: 14 });
    return ops;
  }
  function makeCharStringsIndex(glyphs) {
    var t = new table.Record("CharStrings INDEX", [
      { name: "charStrings", type: "INDEX", value: [] }
    ]);
    for (var i = 0; i < glyphs.length; i += 1) {
      var glyph = glyphs.get(i);
      var ops = glyphToOps(glyph);
      t.charStrings.push({ name: glyph.name, type: "CHARSTRING", value: ops });
    }
    return t;
  }
  function makePrivateDict(attrs, strings) {
    var t = new table.Record("Private DICT", [
      { name: "dict", type: "DICT", value: {} }
    ]);
    t.dict = makeDict(PRIVATE_DICT_META, attrs, strings);
    return t;
  }
  function makeCFFTable(glyphs, options) {
    var t = new table.Table("CFF ", [
      { name: "header", type: "RECORD" },
      { name: "nameIndex", type: "RECORD" },
      { name: "topDictIndex", type: "RECORD" },
      { name: "stringIndex", type: "RECORD" },
      { name: "globalSubrIndex", type: "RECORD" },
      { name: "charsets", type: "RECORD" },
      { name: "charStringsIndex", type: "RECORD" },
      { name: "privateDict", type: "RECORD" }
    ]);
    var fontScale = 1 / options.unitsPerEm;
    var attrs = {
      version: options.version,
      fullName: options.fullName,
      familyName: options.familyName,
      weight: options.weightName,
      fontBBox: options.fontBBox || [0, 0, 0, 0],
      fontMatrix: [fontScale, 0, 0, fontScale, 0, 0],
      charset: 999,
      encoding: 0,
      charStrings: 999,
      private: [0, 999]
    };
    var privateAttrs = {};
    var glyphNames = [];
    var glyph;
    for (var i = 1; i < glyphs.length; i += 1) {
      glyph = glyphs.get(i);
      glyphNames.push(glyph.name);
    }
    var strings = [];
    t.header = makeHeader();
    t.nameIndex = makeNameIndex([options.postScriptName]);
    var topDict = makeTopDict(attrs, strings);
    t.topDictIndex = makeTopDictIndex(topDict);
    t.globalSubrIndex = makeGlobalSubrIndex();
    t.charsets = makeCharsets(glyphNames, strings);
    t.charStringsIndex = makeCharStringsIndex(glyphs);
    t.privateDict = makePrivateDict(privateAttrs, strings);
    t.stringIndex = makeStringIndex(strings);
    var startOffset = t.header.sizeOf() + t.nameIndex.sizeOf() + t.topDictIndex.sizeOf() + t.stringIndex.sizeOf() + t.globalSubrIndex.sizeOf();
    attrs.charset = startOffset;
    attrs.encoding = 0;
    attrs.charStrings = attrs.charset + t.charsets.sizeOf();
    attrs.private[1] = attrs.charStrings + t.charStringsIndex.sizeOf();
    topDict = makeTopDict(attrs, strings);
    t.topDictIndex = makeTopDictIndex(topDict);
    return t;
  }
  var cff = { parse: parseCFFTable, make: makeCFFTable };
  function parseHeadTable(data, start) {
    var head2 = {};
    var p = new parse.Parser(data, start);
    head2.version = p.parseVersion();
    head2.fontRevision = Math.round(p.parseFixed() * 1e3) / 1e3;
    head2.checkSumAdjustment = p.parseULong();
    head2.magicNumber = p.parseULong();
    check.argument(head2.magicNumber === 1594834165, "Font header has wrong magic number.");
    head2.flags = p.parseUShort();
    head2.unitsPerEm = p.parseUShort();
    head2.created = p.parseLongDateTime();
    head2.modified = p.parseLongDateTime();
    head2.xMin = p.parseShort();
    head2.yMin = p.parseShort();
    head2.xMax = p.parseShort();
    head2.yMax = p.parseShort();
    head2.macStyle = p.parseUShort();
    head2.lowestRecPPEM = p.parseUShort();
    head2.fontDirectionHint = p.parseShort();
    head2.indexToLocFormat = p.parseShort();
    head2.glyphDataFormat = p.parseShort();
    return head2;
  }
  function makeHeadTable(options) {
    var timestamp = Math.round((/* @__PURE__ */ new Date()).getTime() / 1e3) + 2082844800;
    var createdTimestamp = timestamp;
    if (options.createdTimestamp) {
      createdTimestamp = options.createdTimestamp + 2082844800;
    }
    return new table.Table("head", [
      { name: "version", type: "FIXED", value: 65536 },
      { name: "fontRevision", type: "FIXED", value: 65536 },
      { name: "checkSumAdjustment", type: "ULONG", value: 0 },
      { name: "magicNumber", type: "ULONG", value: 1594834165 },
      { name: "flags", type: "USHORT", value: 0 },
      { name: "unitsPerEm", type: "USHORT", value: 1e3 },
      { name: "created", type: "LONGDATETIME", value: createdTimestamp },
      { name: "modified", type: "LONGDATETIME", value: timestamp },
      { name: "xMin", type: "SHORT", value: 0 },
      { name: "yMin", type: "SHORT", value: 0 },
      { name: "xMax", type: "SHORT", value: 0 },
      { name: "yMax", type: "SHORT", value: 0 },
      { name: "macStyle", type: "USHORT", value: 0 },
      { name: "lowestRecPPEM", type: "USHORT", value: 0 },
      { name: "fontDirectionHint", type: "SHORT", value: 2 },
      { name: "indexToLocFormat", type: "SHORT", value: 0 },
      { name: "glyphDataFormat", type: "SHORT", value: 0 }
    ], options);
  }
  var head = { parse: parseHeadTable, make: makeHeadTable };
  function parseHheaTable(data, start) {
    var hhea2 = {};
    var p = new parse.Parser(data, start);
    hhea2.version = p.parseVersion();
    hhea2.ascender = p.parseShort();
    hhea2.descender = p.parseShort();
    hhea2.lineGap = p.parseShort();
    hhea2.advanceWidthMax = p.parseUShort();
    hhea2.minLeftSideBearing = p.parseShort();
    hhea2.minRightSideBearing = p.parseShort();
    hhea2.xMaxExtent = p.parseShort();
    hhea2.caretSlopeRise = p.parseShort();
    hhea2.caretSlopeRun = p.parseShort();
    hhea2.caretOffset = p.parseShort();
    p.relativeOffset += 8;
    hhea2.metricDataFormat = p.parseShort();
    hhea2.numberOfHMetrics = p.parseUShort();
    return hhea2;
  }
  function makeHheaTable(options) {
    return new table.Table("hhea", [
      { name: "version", type: "FIXED", value: 65536 },
      { name: "ascender", type: "FWORD", value: 0 },
      { name: "descender", type: "FWORD", value: 0 },
      { name: "lineGap", type: "FWORD", value: 0 },
      { name: "advanceWidthMax", type: "UFWORD", value: 0 },
      { name: "minLeftSideBearing", type: "FWORD", value: 0 },
      { name: "minRightSideBearing", type: "FWORD", value: 0 },
      { name: "xMaxExtent", type: "FWORD", value: 0 },
      { name: "caretSlopeRise", type: "SHORT", value: 1 },
      { name: "caretSlopeRun", type: "SHORT", value: 0 },
      { name: "caretOffset", type: "SHORT", value: 0 },
      { name: "reserved1", type: "SHORT", value: 0 },
      { name: "reserved2", type: "SHORT", value: 0 },
      { name: "reserved3", type: "SHORT", value: 0 },
      { name: "reserved4", type: "SHORT", value: 0 },
      { name: "metricDataFormat", type: "SHORT", value: 0 },
      { name: "numberOfHMetrics", type: "USHORT", value: 0 }
    ], options);
  }
  var hhea = { parse: parseHheaTable, make: makeHheaTable };
  function parseHmtxTableAll(data, start, numMetrics, numGlyphs, glyphs) {
    var advanceWidth;
    var leftSideBearing;
    var p = new parse.Parser(data, start);
    for (var i = 0; i < numGlyphs; i += 1) {
      if (i < numMetrics) {
        advanceWidth = p.parseUShort();
        leftSideBearing = p.parseShort();
      }
      var glyph = glyphs.get(i);
      glyph.advanceWidth = advanceWidth;
      glyph.leftSideBearing = leftSideBearing;
    }
  }
  function parseHmtxTableOnLowMemory(font, data, start, numMetrics, numGlyphs) {
    font._hmtxTableData = {};
    var advanceWidth;
    var leftSideBearing;
    var p = new parse.Parser(data, start);
    for (var i = 0; i < numGlyphs; i += 1) {
      if (i < numMetrics) {
        advanceWidth = p.parseUShort();
        leftSideBearing = p.parseShort();
      }
      font._hmtxTableData[i] = {
        advanceWidth,
        leftSideBearing
      };
    }
  }
  function parseHmtxTable(font, data, start, numMetrics, numGlyphs, glyphs, opt) {
    if (opt.lowMemory) {
      parseHmtxTableOnLowMemory(font, data, start, numMetrics, numGlyphs);
    } else {
      parseHmtxTableAll(data, start, numMetrics, numGlyphs, glyphs);
    }
  }
  function makeHmtxTable(glyphs) {
    var t = new table.Table("hmtx", []);
    for (var i = 0; i < glyphs.length; i += 1) {
      var glyph = glyphs.get(i);
      var advanceWidth = glyph.advanceWidth || 0;
      var leftSideBearing = glyph.leftSideBearing || 0;
      t.fields.push({ name: "advanceWidth_" + i, type: "USHORT", value: advanceWidth });
      t.fields.push({ name: "leftSideBearing_" + i, type: "SHORT", value: leftSideBearing });
    }
    return t;
  }
  var hmtx = { parse: parseHmtxTable, make: makeHmtxTable };
  function makeLtagTable(tags) {
    var result = new table.Table("ltag", [
      { name: "version", type: "ULONG", value: 1 },
      { name: "flags", type: "ULONG", value: 0 },
      { name: "numTags", type: "ULONG", value: tags.length }
    ]);
    var stringPool = "";
    var stringPoolOffset = 12 + tags.length * 4;
    for (var i = 0; i < tags.length; ++i) {
      var pos = stringPool.indexOf(tags[i]);
      if (pos < 0) {
        pos = stringPool.length;
        stringPool += tags[i];
      }
      result.fields.push({ name: "offset " + i, type: "USHORT", value: stringPoolOffset + pos });
      result.fields.push({ name: "length " + i, type: "USHORT", value: tags[i].length });
    }
    result.fields.push({ name: "stringPool", type: "CHARARRAY", value: stringPool });
    return result;
  }
  function parseLtagTable(data, start) {
    var p = new parse.Parser(data, start);
    var tableVersion = p.parseULong();
    check.argument(tableVersion === 1, "Unsupported ltag table version.");
    p.skip("uLong", 1);
    var numTags = p.parseULong();
    var tags = [];
    for (var i = 0; i < numTags; i++) {
      var tag = "";
      var offset = start + p.parseUShort();
      var length = p.parseUShort();
      for (var j = offset; j < offset + length; ++j) {
        tag += String.fromCharCode(data.getInt8(j));
      }
      tags.push(tag);
    }
    return tags;
  }
  var ltag = { make: makeLtagTable, parse: parseLtagTable };
  function parseMaxpTable(data, start) {
    var maxp2 = {};
    var p = new parse.Parser(data, start);
    maxp2.version = p.parseVersion();
    maxp2.numGlyphs = p.parseUShort();
    if (maxp2.version === 1) {
      maxp2.maxPoints = p.parseUShort();
      maxp2.maxContours = p.parseUShort();
      maxp2.maxCompositePoints = p.parseUShort();
      maxp2.maxCompositeContours = p.parseUShort();
      maxp2.maxZones = p.parseUShort();
      maxp2.maxTwilightPoints = p.parseUShort();
      maxp2.maxStorage = p.parseUShort();
      maxp2.maxFunctionDefs = p.parseUShort();
      maxp2.maxInstructionDefs = p.parseUShort();
      maxp2.maxStackElements = p.parseUShort();
      maxp2.maxSizeOfInstructions = p.parseUShort();
      maxp2.maxComponentElements = p.parseUShort();
      maxp2.maxComponentDepth = p.parseUShort();
    }
    return maxp2;
  }
  function makeMaxpTable(numGlyphs) {
    return new table.Table("maxp", [
      { name: "version", type: "FIXED", value: 20480 },
      { name: "numGlyphs", type: "USHORT", value: numGlyphs }
    ]);
  }
  var maxp = { parse: parseMaxpTable, make: makeMaxpTable };
  var nameTableNames = [
    "copyright",
    // 0
    "fontFamily",
    // 1
    "fontSubfamily",
    // 2
    "uniqueID",
    // 3
    "fullName",
    // 4
    "version",
    // 5
    "postScriptName",
    // 6
    "trademark",
    // 7
    "manufacturer",
    // 8
    "designer",
    // 9
    "description",
    // 10
    "manufacturerURL",
    // 11
    "designerURL",
    // 12
    "license",
    // 13
    "licenseURL",
    // 14
    "reserved",
    // 15
    "preferredFamily",
    // 16
    "preferredSubfamily",
    // 17
    "compatibleFullName",
    // 18
    "sampleText",
    // 19
    "postScriptFindFontName",
    // 20
    "wwsFamily",
    // 21
    "wwsSubfamily"
    // 22
  ];
  var macLanguages = {
    0: "en",
    1: "fr",
    2: "de",
    3: "it",
    4: "nl",
    5: "sv",
    6: "es",
    7: "da",
    8: "pt",
    9: "no",
    10: "he",
    11: "ja",
    12: "ar",
    13: "fi",
    14: "el",
    15: "is",
    16: "mt",
    17: "tr",
    18: "hr",
    19: "zh-Hant",
    20: "ur",
    21: "hi",
    22: "th",
    23: "ko",
    24: "lt",
    25: "pl",
    26: "hu",
    27: "es",
    28: "lv",
    29: "se",
    30: "fo",
    31: "fa",
    32: "ru",
    33: "zh",
    34: "nl-BE",
    35: "ga",
    36: "sq",
    37: "ro",
    38: "cz",
    39: "sk",
    40: "si",
    41: "yi",
    42: "sr",
    43: "mk",
    44: "bg",
    45: "uk",
    46: "be",
    47: "uz",
    48: "kk",
    49: "az-Cyrl",
    50: "az-Arab",
    51: "hy",
    52: "ka",
    53: "mo",
    54: "ky",
    55: "tg",
    56: "tk",
    57: "mn-CN",
    58: "mn",
    59: "ps",
    60: "ks",
    61: "ku",
    62: "sd",
    63: "bo",
    64: "ne",
    65: "sa",
    66: "mr",
    67: "bn",
    68: "as",
    69: "gu",
    70: "pa",
    71: "or",
    72: "ml",
    73: "kn",
    74: "ta",
    75: "te",
    76: "si",
    77: "my",
    78: "km",
    79: "lo",
    80: "vi",
    81: "id",
    82: "tl",
    83: "ms",
    84: "ms-Arab",
    85: "am",
    86: "ti",
    87: "om",
    88: "so",
    89: "sw",
    90: "rw",
    91: "rn",
    92: "ny",
    93: "mg",
    94: "eo",
    128: "cy",
    129: "eu",
    130: "ca",
    131: "la",
    132: "qu",
    133: "gn",
    134: "ay",
    135: "tt",
    136: "ug",
    137: "dz",
    138: "jv",
    139: "su",
    140: "gl",
    141: "af",
    142: "br",
    143: "iu",
    144: "gd",
    145: "gv",
    146: "ga",
    147: "to",
    148: "el-polyton",
    149: "kl",
    150: "az",
    151: "nn"
  };
  var macLanguageToScript = {
    0: 0,
    // langEnglish → smRoman
    1: 0,
    // langFrench → smRoman
    2: 0,
    // langGerman → smRoman
    3: 0,
    // langItalian → smRoman
    4: 0,
    // langDutch → smRoman
    5: 0,
    // langSwedish → smRoman
    6: 0,
    // langSpanish → smRoman
    7: 0,
    // langDanish → smRoman
    8: 0,
    // langPortuguese → smRoman
    9: 0,
    // langNorwegian → smRoman
    10: 5,
    // langHebrew → smHebrew
    11: 1,
    // langJapanese → smJapanese
    12: 4,
    // langArabic → smArabic
    13: 0,
    // langFinnish → smRoman
    14: 6,
    // langGreek → smGreek
    15: 0,
    // langIcelandic → smRoman (modified)
    16: 0,
    // langMaltese → smRoman
    17: 0,
    // langTurkish → smRoman (modified)
    18: 0,
    // langCroatian → smRoman (modified)
    19: 2,
    // langTradChinese → smTradChinese
    20: 4,
    // langUrdu → smArabic
    21: 9,
    // langHindi → smDevanagari
    22: 21,
    // langThai → smThai
    23: 3,
    // langKorean → smKorean
    24: 29,
    // langLithuanian → smCentralEuroRoman
    25: 29,
    // langPolish → smCentralEuroRoman
    26: 29,
    // langHungarian → smCentralEuroRoman
    27: 29,
    // langEstonian → smCentralEuroRoman
    28: 29,
    // langLatvian → smCentralEuroRoman
    29: 0,
    // langSami → smRoman
    30: 0,
    // langFaroese → smRoman (modified)
    31: 4,
    // langFarsi → smArabic (modified)
    32: 7,
    // langRussian → smCyrillic
    33: 25,
    // langSimpChinese → smSimpChinese
    34: 0,
    // langFlemish → smRoman
    35: 0,
    // langIrishGaelic → smRoman (modified)
    36: 0,
    // langAlbanian → smRoman
    37: 0,
    // langRomanian → smRoman (modified)
    38: 29,
    // langCzech → smCentralEuroRoman
    39: 29,
    // langSlovak → smCentralEuroRoman
    40: 0,
    // langSlovenian → smRoman (modified)
    41: 5,
    // langYiddish → smHebrew
    42: 7,
    // langSerbian → smCyrillic
    43: 7,
    // langMacedonian → smCyrillic
    44: 7,
    // langBulgarian → smCyrillic
    45: 7,
    // langUkrainian → smCyrillic (modified)
    46: 7,
    // langByelorussian → smCyrillic
    47: 7,
    // langUzbek → smCyrillic
    48: 7,
    // langKazakh → smCyrillic
    49: 7,
    // langAzerbaijani → smCyrillic
    50: 4,
    // langAzerbaijanAr → smArabic
    51: 24,
    // langArmenian → smArmenian
    52: 23,
    // langGeorgian → smGeorgian
    53: 7,
    // langMoldavian → smCyrillic
    54: 7,
    // langKirghiz → smCyrillic
    55: 7,
    // langTajiki → smCyrillic
    56: 7,
    // langTurkmen → smCyrillic
    57: 27,
    // langMongolian → smMongolian
    58: 7,
    // langMongolianCyr → smCyrillic
    59: 4,
    // langPashto → smArabic
    60: 4,
    // langKurdish → smArabic
    61: 4,
    // langKashmiri → smArabic
    62: 4,
    // langSindhi → smArabic
    63: 26,
    // langTibetan → smTibetan
    64: 9,
    // langNepali → smDevanagari
    65: 9,
    // langSanskrit → smDevanagari
    66: 9,
    // langMarathi → smDevanagari
    67: 13,
    // langBengali → smBengali
    68: 13,
    // langAssamese → smBengali
    69: 11,
    // langGujarati → smGujarati
    70: 10,
    // langPunjabi → smGurmukhi
    71: 12,
    // langOriya → smOriya
    72: 17,
    // langMalayalam → smMalayalam
    73: 16,
    // langKannada → smKannada
    74: 14,
    // langTamil → smTamil
    75: 15,
    // langTelugu → smTelugu
    76: 18,
    // langSinhalese → smSinhalese
    77: 19,
    // langBurmese → smBurmese
    78: 20,
    // langKhmer → smKhmer
    79: 22,
    // langLao → smLao
    80: 30,
    // langVietnamese → smVietnamese
    81: 0,
    // langIndonesian → smRoman
    82: 0,
    // langTagalog → smRoman
    83: 0,
    // langMalayRoman → smRoman
    84: 4,
    // langMalayArabic → smArabic
    85: 28,
    // langAmharic → smEthiopic
    86: 28,
    // langTigrinya → smEthiopic
    87: 28,
    // langOromo → smEthiopic
    88: 0,
    // langSomali → smRoman
    89: 0,
    // langSwahili → smRoman
    90: 0,
    // langKinyarwanda → smRoman
    91: 0,
    // langRundi → smRoman
    92: 0,
    // langNyanja → smRoman
    93: 0,
    // langMalagasy → smRoman
    94: 0,
    // langEsperanto → smRoman
    128: 0,
    // langWelsh → smRoman (modified)
    129: 0,
    // langBasque → smRoman
    130: 0,
    // langCatalan → smRoman
    131: 0,
    // langLatin → smRoman
    132: 0,
    // langQuechua → smRoman
    133: 0,
    // langGuarani → smRoman
    134: 0,
    // langAymara → smRoman
    135: 7,
    // langTatar → smCyrillic
    136: 4,
    // langUighur → smArabic
    137: 26,
    // langDzongkha → smTibetan
    138: 0,
    // langJavaneseRom → smRoman
    139: 0,
    // langSundaneseRom → smRoman
    140: 0,
    // langGalician → smRoman
    141: 0,
    // langAfrikaans → smRoman
    142: 0,
    // langBreton → smRoman (modified)
    143: 28,
    // langInuktitut → smEthiopic (modified)
    144: 0,
    // langScottishGaelic → smRoman (modified)
    145: 0,
    // langManxGaelic → smRoman (modified)
    146: 0,
    // langIrishGaelicScript → smRoman (modified)
    147: 0,
    // langTongan → smRoman
    148: 6,
    // langGreekAncient → smRoman
    149: 0,
    // langGreenlandic → smRoman
    150: 0,
    // langAzerbaijanRoman → smRoman
    151: 0
    // langNynorsk → smRoman
  };
  var windowsLanguages = {
    1078: "af",
    1052: "sq",
    1156: "gsw",
    1118: "am",
    5121: "ar-DZ",
    15361: "ar-BH",
    3073: "ar",
    2049: "ar-IQ",
    11265: "ar-JO",
    13313: "ar-KW",
    12289: "ar-LB",
    4097: "ar-LY",
    6145: "ary",
    8193: "ar-OM",
    16385: "ar-QA",
    1025: "ar-SA",
    10241: "ar-SY",
    7169: "aeb",
    14337: "ar-AE",
    9217: "ar-YE",
    1067: "hy",
    1101: "as",
    2092: "az-Cyrl",
    1068: "az",
    1133: "ba",
    1069: "eu",
    1059: "be",
    2117: "bn",
    1093: "bn-IN",
    8218: "bs-Cyrl",
    5146: "bs",
    1150: "br",
    1026: "bg",
    1027: "ca",
    3076: "zh-HK",
    5124: "zh-MO",
    2052: "zh",
    4100: "zh-SG",
    1028: "zh-TW",
    1155: "co",
    1050: "hr",
    4122: "hr-BA",
    1029: "cs",
    1030: "da",
    1164: "prs",
    1125: "dv",
    2067: "nl-BE",
    1043: "nl",
    3081: "en-AU",
    10249: "en-BZ",
    4105: "en-CA",
    9225: "en-029",
    16393: "en-IN",
    6153: "en-IE",
    8201: "en-JM",
    17417: "en-MY",
    5129: "en-NZ",
    13321: "en-PH",
    18441: "en-SG",
    7177: "en-ZA",
    11273: "en-TT",
    2057: "en-GB",
    1033: "en",
    12297: "en-ZW",
    1061: "et",
    1080: "fo",
    1124: "fil",
    1035: "fi",
    2060: "fr-BE",
    3084: "fr-CA",
    1036: "fr",
    5132: "fr-LU",
    6156: "fr-MC",
    4108: "fr-CH",
    1122: "fy",
    1110: "gl",
    1079: "ka",
    3079: "de-AT",
    1031: "de",
    5127: "de-LI",
    4103: "de-LU",
    2055: "de-CH",
    1032: "el",
    1135: "kl",
    1095: "gu",
    1128: "ha",
    1037: "he",
    1081: "hi",
    1038: "hu",
    1039: "is",
    1136: "ig",
    1057: "id",
    1117: "iu",
    2141: "iu-Latn",
    2108: "ga",
    1076: "xh",
    1077: "zu",
    1040: "it",
    2064: "it-CH",
    1041: "ja",
    1099: "kn",
    1087: "kk",
    1107: "km",
    1158: "quc",
    1159: "rw",
    1089: "sw",
    1111: "kok",
    1042: "ko",
    1088: "ky",
    1108: "lo",
    1062: "lv",
    1063: "lt",
    2094: "dsb",
    1134: "lb",
    1071: "mk",
    2110: "ms-BN",
    1086: "ms",
    1100: "ml",
    1082: "mt",
    1153: "mi",
    1146: "arn",
    1102: "mr",
    1148: "moh",
    1104: "mn",
    2128: "mn-CN",
    1121: "ne",
    1044: "nb",
    2068: "nn",
    1154: "oc",
    1096: "or",
    1123: "ps",
    1045: "pl",
    1046: "pt",
    2070: "pt-PT",
    1094: "pa",
    1131: "qu-BO",
    2155: "qu-EC",
    3179: "qu",
    1048: "ro",
    1047: "rm",
    1049: "ru",
    9275: "smn",
    4155: "smj-NO",
    5179: "smj",
    3131: "se-FI",
    1083: "se",
    2107: "se-SE",
    8251: "sms",
    6203: "sma-NO",
    7227: "sms",
    1103: "sa",
    7194: "sr-Cyrl-BA",
    3098: "sr",
    6170: "sr-Latn-BA",
    2074: "sr-Latn",
    1132: "nso",
    1074: "tn",
    1115: "si",
    1051: "sk",
    1060: "sl",
    11274: "es-AR",
    16394: "es-BO",
    13322: "es-CL",
    9226: "es-CO",
    5130: "es-CR",
    7178: "es-DO",
    12298: "es-EC",
    17418: "es-SV",
    4106: "es-GT",
    18442: "es-HN",
    2058: "es-MX",
    19466: "es-NI",
    6154: "es-PA",
    15370: "es-PY",
    10250: "es-PE",
    20490: "es-PR",
    // Microsoft has defined two different language codes for
    // “Spanish with modern sorting” and “Spanish with traditional
    // sorting”. This makes sense for collation APIs, and it would be
    // possible to express this in BCP 47 language tags via Unicode
    // extensions (eg., es-u-co-trad is Spanish with traditional
    // sorting). However, for storing names in fonts, the distinction
    // does not make sense, so we give “es” in both cases.
    3082: "es",
    1034: "es",
    21514: "es-US",
    14346: "es-UY",
    8202: "es-VE",
    2077: "sv-FI",
    1053: "sv",
    1114: "syr",
    1064: "tg",
    2143: "tzm",
    1097: "ta",
    1092: "tt",
    1098: "te",
    1054: "th",
    1105: "bo",
    1055: "tr",
    1090: "tk",
    1152: "ug",
    1058: "uk",
    1070: "hsb",
    1056: "ur",
    2115: "uz-Cyrl",
    1091: "uz",
    1066: "vi",
    1106: "cy",
    1160: "wo",
    1157: "sah",
    1144: "ii",
    1130: "yo"
  };
  function getLanguageCode(platformID, languageID, ltag2) {
    switch (platformID) {
      case 0:
        if (languageID === 65535) {
          return "und";
        } else if (ltag2) {
          return ltag2[languageID];
        }
        break;
      case 1:
        return macLanguages[languageID];
      case 3:
        return windowsLanguages[languageID];
    }
    return void 0;
  }
  var utf16 = "utf-16";
  var macScriptEncodings = {
    0: "macintosh",
    // smRoman
    1: "x-mac-japanese",
    // smJapanese
    2: "x-mac-chinesetrad",
    // smTradChinese
    3: "x-mac-korean",
    // smKorean
    6: "x-mac-greek",
    // smGreek
    7: "x-mac-cyrillic",
    // smCyrillic
    9: "x-mac-devanagai",
    // smDevanagari
    10: "x-mac-gurmukhi",
    // smGurmukhi
    11: "x-mac-gujarati",
    // smGujarati
    12: "x-mac-oriya",
    // smOriya
    13: "x-mac-bengali",
    // smBengali
    14: "x-mac-tamil",
    // smTamil
    15: "x-mac-telugu",
    // smTelugu
    16: "x-mac-kannada",
    // smKannada
    17: "x-mac-malayalam",
    // smMalayalam
    18: "x-mac-sinhalese",
    // smSinhalese
    19: "x-mac-burmese",
    // smBurmese
    20: "x-mac-khmer",
    // smKhmer
    21: "x-mac-thai",
    // smThai
    22: "x-mac-lao",
    // smLao
    23: "x-mac-georgian",
    // smGeorgian
    24: "x-mac-armenian",
    // smArmenian
    25: "x-mac-chinesesimp",
    // smSimpChinese
    26: "x-mac-tibetan",
    // smTibetan
    27: "x-mac-mongolian",
    // smMongolian
    28: "x-mac-ethiopic",
    // smEthiopic
    29: "x-mac-ce",
    // smCentralEuroRoman
    30: "x-mac-vietnamese",
    // smVietnamese
    31: "x-mac-extarabic"
    // smExtArabic
  };
  var macLanguageEncodings = {
    15: "x-mac-icelandic",
    // langIcelandic
    17: "x-mac-turkish",
    // langTurkish
    18: "x-mac-croatian",
    // langCroatian
    24: "x-mac-ce",
    // langLithuanian
    25: "x-mac-ce",
    // langPolish
    26: "x-mac-ce",
    // langHungarian
    27: "x-mac-ce",
    // langEstonian
    28: "x-mac-ce",
    // langLatvian
    30: "x-mac-icelandic",
    // langFaroese
    37: "x-mac-romanian",
    // langRomanian
    38: "x-mac-ce",
    // langCzech
    39: "x-mac-ce",
    // langSlovak
    40: "x-mac-ce",
    // langSlovenian
    143: "x-mac-inuit",
    // langInuktitut
    146: "x-mac-gaelic"
    // langIrishGaelicScript
  };
  function getEncoding(platformID, encodingID, languageID) {
    switch (platformID) {
      case 0:
        return utf16;
      case 1:
        return macLanguageEncodings[languageID] || macScriptEncodings[encodingID];
      case 3:
        if (encodingID === 1 || encodingID === 10) {
          return utf16;
        }
        break;
    }
    return void 0;
  }
  function parseNameTable(data, start, ltag2) {
    var name = {};
    var p = new parse.Parser(data, start);
    var format = p.parseUShort();
    var count = p.parseUShort();
    var stringOffset = p.offset + p.parseUShort();
    for (var i = 0; i < count; i++) {
      var platformID = p.parseUShort();
      var encodingID = p.parseUShort();
      var languageID = p.parseUShort();
      var nameID = p.parseUShort();
      var property = nameTableNames[nameID] || nameID;
      var byteLength = p.parseUShort();
      var offset = p.parseUShort();
      var language = getLanguageCode(platformID, languageID, ltag2);
      var encoding = getEncoding(platformID, encodingID, languageID);
      if (encoding !== void 0 && language !== void 0) {
        var text = void 0;
        if (encoding === utf16) {
          text = decode.UTF16(data, stringOffset + offset, byteLength);
        } else {
          text = decode.MACSTRING(data, stringOffset + offset, byteLength, encoding);
        }
        if (text) {
          var translations = name[property];
          if (translations === void 0) {
            translations = name[property] = {};
          }
          translations[language] = text;
        }
      }
    }
    var langTagCount = 0;
    if (format === 1) {
      langTagCount = p.parseUShort();
    }
    return name;
  }
  function reverseDict(dict) {
    var result = {};
    for (var key in dict) {
      result[dict[key]] = parseInt(key);
    }
    return result;
  }
  function makeNameRecord(platformID, encodingID, languageID, nameID, length, offset) {
    return new table.Record("NameRecord", [
      { name: "platformID", type: "USHORT", value: platformID },
      { name: "encodingID", type: "USHORT", value: encodingID },
      { name: "languageID", type: "USHORT", value: languageID },
      { name: "nameID", type: "USHORT", value: nameID },
      { name: "length", type: "USHORT", value: length },
      { name: "offset", type: "USHORT", value: offset }
    ]);
  }
  function findSubArray(needle, haystack) {
    var needleLength = needle.length;
    var limit = haystack.length - needleLength + 1;
    loop:
      for (var pos = 0; pos < limit; pos++) {
        for (; pos < limit; pos++) {
          for (var k = 0; k < needleLength; k++) {
            if (haystack[pos + k] !== needle[k]) {
              continue loop;
            }
          }
          return pos;
        }
      }
    return -1;
  }
  function addStringToPool(s, pool) {
    var offset = findSubArray(s, pool);
    if (offset < 0) {
      offset = pool.length;
      var i = 0;
      var len = s.length;
      for (; i < len; ++i) {
        pool.push(s[i]);
      }
    }
    return offset;
  }
  function makeNameTable(names, ltag2) {
    var nameID;
    var nameIDs = [];
    var namesWithNumericKeys = {};
    var nameTableIds = reverseDict(nameTableNames);
    for (var key in names) {
      var id = nameTableIds[key];
      if (id === void 0) {
        id = key;
      }
      nameID = parseInt(id);
      if (isNaN(nameID)) {
        throw new Error('Name table entry "' + key + '" does not exist, see nameTableNames for complete list.');
      }
      namesWithNumericKeys[nameID] = names[key];
      nameIDs.push(nameID);
    }
    var macLanguageIds = reverseDict(macLanguages);
    var windowsLanguageIds = reverseDict(windowsLanguages);
    var nameRecords = [];
    var stringPool = [];
    for (var i = 0; i < nameIDs.length; i++) {
      nameID = nameIDs[i];
      var translations = namesWithNumericKeys[nameID];
      for (var lang in translations) {
        var text = translations[lang];
        var macPlatform = 1;
        var macLanguage = macLanguageIds[lang];
        var macScript = macLanguageToScript[macLanguage];
        var macEncoding = getEncoding(macPlatform, macScript, macLanguage);
        var macName = encode.MACSTRING(text, macEncoding);
        if (macName === void 0) {
          macPlatform = 0;
          macLanguage = ltag2.indexOf(lang);
          if (macLanguage < 0) {
            macLanguage = ltag2.length;
            ltag2.push(lang);
          }
          macScript = 4;
          macName = encode.UTF16(text);
        }
        var macNameOffset = addStringToPool(macName, stringPool);
        nameRecords.push(makeNameRecord(
          macPlatform,
          macScript,
          macLanguage,
          nameID,
          macName.length,
          macNameOffset
        ));
        var winLanguage = windowsLanguageIds[lang];
        if (winLanguage !== void 0) {
          var winName = encode.UTF16(text);
          var winNameOffset = addStringToPool(winName, stringPool);
          nameRecords.push(makeNameRecord(
            3,
            1,
            winLanguage,
            nameID,
            winName.length,
            winNameOffset
          ));
        }
      }
    }
    nameRecords.sort(function(a, b) {
      return a.platformID - b.platformID || a.encodingID - b.encodingID || a.languageID - b.languageID || a.nameID - b.nameID;
    });
    var t = new table.Table("name", [
      { name: "format", type: "USHORT", value: 0 },
      { name: "count", type: "USHORT", value: nameRecords.length },
      { name: "stringOffset", type: "USHORT", value: 6 + nameRecords.length * 12 }
    ]);
    for (var r = 0; r < nameRecords.length; r++) {
      t.fields.push({ name: "record_" + r, type: "RECORD", value: nameRecords[r] });
    }
    t.fields.push({ name: "strings", type: "LITERAL", value: stringPool });
    return t;
  }
  var _name = { parse: parseNameTable, make: makeNameTable };
  var unicodeRanges = [
    { begin: 0, end: 127 },
    // Basic Latin
    { begin: 128, end: 255 },
    // Latin-1 Supplement
    { begin: 256, end: 383 },
    // Latin Extended-A
    { begin: 384, end: 591 },
    // Latin Extended-B
    { begin: 592, end: 687 },
    // IPA Extensions
    { begin: 688, end: 767 },
    // Spacing Modifier Letters
    { begin: 768, end: 879 },
    // Combining Diacritical Marks
    { begin: 880, end: 1023 },
    // Greek and Coptic
    { begin: 11392, end: 11519 },
    // Coptic
    { begin: 1024, end: 1279 },
    // Cyrillic
    { begin: 1328, end: 1423 },
    // Armenian
    { begin: 1424, end: 1535 },
    // Hebrew
    { begin: 42240, end: 42559 },
    // Vai
    { begin: 1536, end: 1791 },
    // Arabic
    { begin: 1984, end: 2047 },
    // NKo
    { begin: 2304, end: 2431 },
    // Devanagari
    { begin: 2432, end: 2559 },
    // Bengali
    { begin: 2560, end: 2687 },
    // Gurmukhi
    { begin: 2688, end: 2815 },
    // Gujarati
    { begin: 2816, end: 2943 },
    // Oriya
    { begin: 2944, end: 3071 },
    // Tamil
    { begin: 3072, end: 3199 },
    // Telugu
    { begin: 3200, end: 3327 },
    // Kannada
    { begin: 3328, end: 3455 },
    // Malayalam
    { begin: 3584, end: 3711 },
    // Thai
    { begin: 3712, end: 3839 },
    // Lao
    { begin: 4256, end: 4351 },
    // Georgian
    { begin: 6912, end: 7039 },
    // Balinese
    { begin: 4352, end: 4607 },
    // Hangul Jamo
    { begin: 7680, end: 7935 },
    // Latin Extended Additional
    { begin: 7936, end: 8191 },
    // Greek Extended
    { begin: 8192, end: 8303 },
    // General Punctuation
    { begin: 8304, end: 8351 },
    // Superscripts And Subscripts
    { begin: 8352, end: 8399 },
    // Currency Symbol
    { begin: 8400, end: 8447 },
    // Combining Diacritical Marks For Symbols
    { begin: 8448, end: 8527 },
    // Letterlike Symbols
    { begin: 8528, end: 8591 },
    // Number Forms
    { begin: 8592, end: 8703 },
    // Arrows
    { begin: 8704, end: 8959 },
    // Mathematical Operators
    { begin: 8960, end: 9215 },
    // Miscellaneous Technical
    { begin: 9216, end: 9279 },
    // Control Pictures
    { begin: 9280, end: 9311 },
    // Optical Character Recognition
    { begin: 9312, end: 9471 },
    // Enclosed Alphanumerics
    { begin: 9472, end: 9599 },
    // Box Drawing
    { begin: 9600, end: 9631 },
    // Block Elements
    { begin: 9632, end: 9727 },
    // Geometric Shapes
    { begin: 9728, end: 9983 },
    // Miscellaneous Symbols
    { begin: 9984, end: 10175 },
    // Dingbats
    { begin: 12288, end: 12351 },
    // CJK Symbols And Punctuation
    { begin: 12352, end: 12447 },
    // Hiragana
    { begin: 12448, end: 12543 },
    // Katakana
    { begin: 12544, end: 12591 },
    // Bopomofo
    { begin: 12592, end: 12687 },
    // Hangul Compatibility Jamo
    { begin: 43072, end: 43135 },
    // Phags-pa
    { begin: 12800, end: 13055 },
    // Enclosed CJK Letters And Months
    { begin: 13056, end: 13311 },
    // CJK Compatibility
    { begin: 44032, end: 55215 },
    // Hangul Syllables
    { begin: 55296, end: 57343 },
    // Non-Plane 0 *
    { begin: 67840, end: 67871 },
    // Phoenicia
    { begin: 19968, end: 40959 },
    // CJK Unified Ideographs
    { begin: 57344, end: 63743 },
    // Private Use Area (plane 0)
    { begin: 12736, end: 12783 },
    // CJK Strokes
    { begin: 64256, end: 64335 },
    // Alphabetic Presentation Forms
    { begin: 64336, end: 65023 },
    // Arabic Presentation Forms-A
    { begin: 65056, end: 65071 },
    // Combining Half Marks
    { begin: 65040, end: 65055 },
    // Vertical Forms
    { begin: 65104, end: 65135 },
    // Small Form Variants
    { begin: 65136, end: 65279 },
    // Arabic Presentation Forms-B
    { begin: 65280, end: 65519 },
    // Halfwidth And Fullwidth Forms
    { begin: 65520, end: 65535 },
    // Specials
    { begin: 3840, end: 4095 },
    // Tibetan
    { begin: 1792, end: 1871 },
    // Syriac
    { begin: 1920, end: 1983 },
    // Thaana
    { begin: 3456, end: 3583 },
    // Sinhala
    { begin: 4096, end: 4255 },
    // Myanmar
    { begin: 4608, end: 4991 },
    // Ethiopic
    { begin: 5024, end: 5119 },
    // Cherokee
    { begin: 5120, end: 5759 },
    // Unified Canadian Aboriginal Syllabics
    { begin: 5760, end: 5791 },
    // Ogham
    { begin: 5792, end: 5887 },
    // Runic
    { begin: 6016, end: 6143 },
    // Khmer
    { begin: 6144, end: 6319 },
    // Mongolian
    { begin: 10240, end: 10495 },
    // Braille Patterns
    { begin: 40960, end: 42127 },
    // Yi Syllables
    { begin: 5888, end: 5919 },
    // Tagalog
    { begin: 66304, end: 66351 },
    // Old Italic
    { begin: 66352, end: 66383 },
    // Gothic
    { begin: 66560, end: 66639 },
    // Deseret
    { begin: 118784, end: 119039 },
    // Byzantine Musical Symbols
    { begin: 119808, end: 120831 },
    // Mathematical Alphanumeric Symbols
    { begin: 1044480, end: 1048573 },
    // Private Use (plane 15)
    { begin: 65024, end: 65039 },
    // Variation Selectors
    { begin: 917504, end: 917631 },
    // Tags
    { begin: 6400, end: 6479 },
    // Limbu
    { begin: 6480, end: 6527 },
    // Tai Le
    { begin: 6528, end: 6623 },
    // New Tai Lue
    { begin: 6656, end: 6687 },
    // Buginese
    { begin: 11264, end: 11359 },
    // Glagolitic
    { begin: 11568, end: 11647 },
    // Tifinagh
    { begin: 19904, end: 19967 },
    // Yijing Hexagram Symbols
    { begin: 43008, end: 43055 },
    // Syloti Nagri
    { begin: 65536, end: 65663 },
    // Linear B Syllabary
    { begin: 65856, end: 65935 },
    // Ancient Greek Numbers
    { begin: 66432, end: 66463 },
    // Ugaritic
    { begin: 66464, end: 66527 },
    // Old Persian
    { begin: 66640, end: 66687 },
    // Shavian
    { begin: 66688, end: 66735 },
    // Osmanya
    { begin: 67584, end: 67647 },
    // Cypriot Syllabary
    { begin: 68096, end: 68191 },
    // Kharoshthi
    { begin: 119552, end: 119647 },
    // Tai Xuan Jing Symbols
    { begin: 73728, end: 74751 },
    // Cuneiform
    { begin: 119648, end: 119679 },
    // Counting Rod Numerals
    { begin: 7040, end: 7103 },
    // Sundanese
    { begin: 7168, end: 7247 },
    // Lepcha
    { begin: 7248, end: 7295 },
    // Ol Chiki
    { begin: 43136, end: 43231 },
    // Saurashtra
    { begin: 43264, end: 43311 },
    // Kayah Li
    { begin: 43312, end: 43359 },
    // Rejang
    { begin: 43520, end: 43615 },
    // Cham
    { begin: 65936, end: 65999 },
    // Ancient Symbols
    { begin: 66e3, end: 66047 },
    // Phaistos Disc
    { begin: 66208, end: 66271 },
    // Carian
    { begin: 127024, end: 127135 }
    // Domino Tiles
  ];
  function getUnicodeRange(unicode) {
    for (var i = 0; i < unicodeRanges.length; i += 1) {
      var range = unicodeRanges[i];
      if (unicode >= range.begin && unicode < range.end) {
        return i;
      }
    }
    return -1;
  }
  function parseOS2Table(data, start) {
    var os22 = {};
    var p = new parse.Parser(data, start);
    os22.version = p.parseUShort();
    os22.xAvgCharWidth = p.parseShort();
    os22.usWeightClass = p.parseUShort();
    os22.usWidthClass = p.parseUShort();
    os22.fsType = p.parseUShort();
    os22.ySubscriptXSize = p.parseShort();
    os22.ySubscriptYSize = p.parseShort();
    os22.ySubscriptXOffset = p.parseShort();
    os22.ySubscriptYOffset = p.parseShort();
    os22.ySuperscriptXSize = p.parseShort();
    os22.ySuperscriptYSize = p.parseShort();
    os22.ySuperscriptXOffset = p.parseShort();
    os22.ySuperscriptYOffset = p.parseShort();
    os22.yStrikeoutSize = p.parseShort();
    os22.yStrikeoutPosition = p.parseShort();
    os22.sFamilyClass = p.parseShort();
    os22.panose = [];
    for (var i = 0; i < 10; i++) {
      os22.panose[i] = p.parseByte();
    }
    os22.ulUnicodeRange1 = p.parseULong();
    os22.ulUnicodeRange2 = p.parseULong();
    os22.ulUnicodeRange3 = p.parseULong();
    os22.ulUnicodeRange4 = p.parseULong();
    os22.achVendID = String.fromCharCode(p.parseByte(), p.parseByte(), p.parseByte(), p.parseByte());
    os22.fsSelection = p.parseUShort();
    os22.usFirstCharIndex = p.parseUShort();
    os22.usLastCharIndex = p.parseUShort();
    os22.sTypoAscender = p.parseShort();
    os22.sTypoDescender = p.parseShort();
    os22.sTypoLineGap = p.parseShort();
    os22.usWinAscent = p.parseUShort();
    os22.usWinDescent = p.parseUShort();
    if (os22.version >= 1) {
      os22.ulCodePageRange1 = p.parseULong();
      os22.ulCodePageRange2 = p.parseULong();
    }
    if (os22.version >= 2) {
      os22.sxHeight = p.parseShort();
      os22.sCapHeight = p.parseShort();
      os22.usDefaultChar = p.parseUShort();
      os22.usBreakChar = p.parseUShort();
      os22.usMaxContent = p.parseUShort();
    }
    return os22;
  }
  function makeOS2Table(options) {
    return new table.Table("OS/2", [
      { name: "version", type: "USHORT", value: 3 },
      { name: "xAvgCharWidth", type: "SHORT", value: 0 },
      { name: "usWeightClass", type: "USHORT", value: 0 },
      { name: "usWidthClass", type: "USHORT", value: 0 },
      { name: "fsType", type: "USHORT", value: 0 },
      { name: "ySubscriptXSize", type: "SHORT", value: 650 },
      { name: "ySubscriptYSize", type: "SHORT", value: 699 },
      { name: "ySubscriptXOffset", type: "SHORT", value: 0 },
      { name: "ySubscriptYOffset", type: "SHORT", value: 140 },
      { name: "ySuperscriptXSize", type: "SHORT", value: 650 },
      { name: "ySuperscriptYSize", type: "SHORT", value: 699 },
      { name: "ySuperscriptXOffset", type: "SHORT", value: 0 },
      { name: "ySuperscriptYOffset", type: "SHORT", value: 479 },
      { name: "yStrikeoutSize", type: "SHORT", value: 49 },
      { name: "yStrikeoutPosition", type: "SHORT", value: 258 },
      { name: "sFamilyClass", type: "SHORT", value: 0 },
      { name: "bFamilyType", type: "BYTE", value: 0 },
      { name: "bSerifStyle", type: "BYTE", value: 0 },
      { name: "bWeight", type: "BYTE", value: 0 },
      { name: "bProportion", type: "BYTE", value: 0 },
      { name: "bContrast", type: "BYTE", value: 0 },
      { name: "bStrokeVariation", type: "BYTE", value: 0 },
      { name: "bArmStyle", type: "BYTE", value: 0 },
      { name: "bLetterform", type: "BYTE", value: 0 },
      { name: "bMidline", type: "BYTE", value: 0 },
      { name: "bXHeight", type: "BYTE", value: 0 },
      { name: "ulUnicodeRange1", type: "ULONG", value: 0 },
      { name: "ulUnicodeRange2", type: "ULONG", value: 0 },
      { name: "ulUnicodeRange3", type: "ULONG", value: 0 },
      { name: "ulUnicodeRange4", type: "ULONG", value: 0 },
      { name: "achVendID", type: "CHARARRAY", value: "XXXX" },
      { name: "fsSelection", type: "USHORT", value: 0 },
      { name: "usFirstCharIndex", type: "USHORT", value: 0 },
      { name: "usLastCharIndex", type: "USHORT", value: 0 },
      { name: "sTypoAscender", type: "SHORT", value: 0 },
      { name: "sTypoDescender", type: "SHORT", value: 0 },
      { name: "sTypoLineGap", type: "SHORT", value: 0 },
      { name: "usWinAscent", type: "USHORT", value: 0 },
      { name: "usWinDescent", type: "USHORT", value: 0 },
      { name: "ulCodePageRange1", type: "ULONG", value: 0 },
      { name: "ulCodePageRange2", type: "ULONG", value: 0 },
      { name: "sxHeight", type: "SHORT", value: 0 },
      { name: "sCapHeight", type: "SHORT", value: 0 },
      { name: "usDefaultChar", type: "USHORT", value: 0 },
      { name: "usBreakChar", type: "USHORT", value: 0 },
      { name: "usMaxContext", type: "USHORT", value: 0 }
    ], options);
  }
  var os2 = { parse: parseOS2Table, make: makeOS2Table, unicodeRanges, getUnicodeRange };
  function parsePostTable(data, start) {
    var post2 = {};
    var p = new parse.Parser(data, start);
    post2.version = p.parseVersion();
    post2.italicAngle = p.parseFixed();
    post2.underlinePosition = p.parseShort();
    post2.underlineThickness = p.parseShort();
    post2.isFixedPitch = p.parseULong();
    post2.minMemType42 = p.parseULong();
    post2.maxMemType42 = p.parseULong();
    post2.minMemType1 = p.parseULong();
    post2.maxMemType1 = p.parseULong();
    switch (post2.version) {
      case 1:
        post2.names = standardNames.slice();
        break;
      case 2:
        post2.numberOfGlyphs = p.parseUShort();
        post2.glyphNameIndex = new Array(post2.numberOfGlyphs);
        for (var i = 0; i < post2.numberOfGlyphs; i++) {
          post2.glyphNameIndex[i] = p.parseUShort();
        }
        post2.names = [];
        for (var i$1 = 0; i$1 < post2.numberOfGlyphs; i$1++) {
          if (post2.glyphNameIndex[i$1] >= standardNames.length) {
            var nameLength = p.parseChar();
            post2.names.push(p.parseString(nameLength));
          }
        }
        break;
      case 2.5:
        post2.numberOfGlyphs = p.parseUShort();
        post2.offset = new Array(post2.numberOfGlyphs);
        for (var i$2 = 0; i$2 < post2.numberOfGlyphs; i$2++) {
          post2.offset[i$2] = p.parseChar();
        }
        break;
    }
    return post2;
  }
  function makePostTable() {
    return new table.Table("post", [
      { name: "version", type: "FIXED", value: 196608 },
      { name: "italicAngle", type: "FIXED", value: 0 },
      { name: "underlinePosition", type: "FWORD", value: 0 },
      { name: "underlineThickness", type: "FWORD", value: 0 },
      { name: "isFixedPitch", type: "ULONG", value: 0 },
      { name: "minMemType42", type: "ULONG", value: 0 },
      { name: "maxMemType42", type: "ULONG", value: 0 },
      { name: "minMemType1", type: "ULONG", value: 0 },
      { name: "maxMemType1", type: "ULONG", value: 0 }
    ]);
  }
  var post = { parse: parsePostTable, make: makePostTable };
  var subtableParsers = new Array(9);
  subtableParsers[1] = function parseLookup1() {
    var start = this.offset + this.relativeOffset;
    var substFormat = this.parseUShort();
    if (substFormat === 1) {
      return {
        substFormat: 1,
        coverage: this.parsePointer(Parser2.coverage),
        deltaGlyphId: this.parseUShort()
      };
    } else if (substFormat === 2) {
      return {
        substFormat: 2,
        coverage: this.parsePointer(Parser2.coverage),
        substitute: this.parseOffset16List()
      };
    }
    check.assert(false, "0x" + start.toString(16) + ": lookup type 1 format must be 1 or 2.");
  };
  subtableParsers[2] = function parseLookup2() {
    var substFormat = this.parseUShort();
    check.argument(substFormat === 1, "GSUB Multiple Substitution Subtable identifier-format must be 1");
    return {
      substFormat,
      coverage: this.parsePointer(Parser2.coverage),
      sequences: this.parseListOfLists()
    };
  };
  subtableParsers[3] = function parseLookup3() {
    var substFormat = this.parseUShort();
    check.argument(substFormat === 1, "GSUB Alternate Substitution Subtable identifier-format must be 1");
    return {
      substFormat,
      coverage: this.parsePointer(Parser2.coverage),
      alternateSets: this.parseListOfLists()
    };
  };
  subtableParsers[4] = function parseLookup4() {
    var substFormat = this.parseUShort();
    check.argument(substFormat === 1, "GSUB ligature table identifier-format must be 1");
    return {
      substFormat,
      coverage: this.parsePointer(Parser2.coverage),
      ligatureSets: this.parseListOfLists(function() {
        return {
          ligGlyph: this.parseUShort(),
          components: this.parseUShortList(this.parseUShort() - 1)
        };
      })
    };
  };
  var lookupRecordDesc = {
    sequenceIndex: Parser2.uShort,
    lookupListIndex: Parser2.uShort
  };
  subtableParsers[5] = function parseLookup5() {
    var start = this.offset + this.relativeOffset;
    var substFormat = this.parseUShort();
    if (substFormat === 1) {
      return {
        substFormat,
        coverage: this.parsePointer(Parser2.coverage),
        ruleSets: this.parseListOfLists(function() {
          var glyphCount2 = this.parseUShort();
          var substCount2 = this.parseUShort();
          return {
            input: this.parseUShortList(glyphCount2 - 1),
            lookupRecords: this.parseRecordList(substCount2, lookupRecordDesc)
          };
        })
      };
    } else if (substFormat === 2) {
      return {
        substFormat,
        coverage: this.parsePointer(Parser2.coverage),
        classDef: this.parsePointer(Parser2.classDef),
        classSets: this.parseListOfLists(function() {
          var glyphCount2 = this.parseUShort();
          var substCount2 = this.parseUShort();
          return {
            classes: this.parseUShortList(glyphCount2 - 1),
            lookupRecords: this.parseRecordList(substCount2, lookupRecordDesc)
          };
        })
      };
    } else if (substFormat === 3) {
      var glyphCount = this.parseUShort();
      var substCount = this.parseUShort();
      return {
        substFormat,
        coverages: this.parseList(glyphCount, Parser2.pointer(Parser2.coverage)),
        lookupRecords: this.parseRecordList(substCount, lookupRecordDesc)
      };
    }
    check.assert(false, "0x" + start.toString(16) + ": lookup type 5 format must be 1, 2 or 3.");
  };
  subtableParsers[6] = function parseLookup6() {
    var start = this.offset + this.relativeOffset;
    var substFormat = this.parseUShort();
    if (substFormat === 1) {
      return {
        substFormat: 1,
        coverage: this.parsePointer(Parser2.coverage),
        chainRuleSets: this.parseListOfLists(function() {
          return {
            backtrack: this.parseUShortList(),
            input: this.parseUShortList(this.parseShort() - 1),
            lookahead: this.parseUShortList(),
            lookupRecords: this.parseRecordList(lookupRecordDesc)
          };
        })
      };
    } else if (substFormat === 2) {
      return {
        substFormat: 2,
        coverage: this.parsePointer(Parser2.coverage),
        backtrackClassDef: this.parsePointer(Parser2.classDef),
        inputClassDef: this.parsePointer(Parser2.classDef),
        lookaheadClassDef: this.parsePointer(Parser2.classDef),
        chainClassSet: this.parseListOfLists(function() {
          return {
            backtrack: this.parseUShortList(),
            input: this.parseUShortList(this.parseShort() - 1),
            lookahead: this.parseUShortList(),
            lookupRecords: this.parseRecordList(lookupRecordDesc)
          };
        })
      };
    } else if (substFormat === 3) {
      return {
        substFormat: 3,
        backtrackCoverage: this.parseList(Parser2.pointer(Parser2.coverage)),
        inputCoverage: this.parseList(Parser2.pointer(Parser2.coverage)),
        lookaheadCoverage: this.parseList(Parser2.pointer(Parser2.coverage)),
        lookupRecords: this.parseRecordList(lookupRecordDesc)
      };
    }
    check.assert(false, "0x" + start.toString(16) + ": lookup type 6 format must be 1, 2 or 3.");
  };
  subtableParsers[7] = function parseLookup7() {
    var substFormat = this.parseUShort();
    check.argument(substFormat === 1, "GSUB Extension Substitution subtable identifier-format must be 1");
    var extensionLookupType = this.parseUShort();
    var extensionParser = new Parser2(this.data, this.offset + this.parseULong());
    return {
      substFormat: 1,
      lookupType: extensionLookupType,
      extension: subtableParsers[extensionLookupType].call(extensionParser)
    };
  };
  subtableParsers[8] = function parseLookup8() {
    var substFormat = this.parseUShort();
    check.argument(substFormat === 1, "GSUB Reverse Chaining Contextual Single Substitution Subtable identifier-format must be 1");
    return {
      substFormat,
      coverage: this.parsePointer(Parser2.coverage),
      backtrackCoverage: this.parseList(Parser2.pointer(Parser2.coverage)),
      lookaheadCoverage: this.parseList(Parser2.pointer(Parser2.coverage)),
      substitutes: this.parseUShortList()
    };
  };
  function parseGsubTable(data, start) {
    start = start || 0;
    var p = new Parser2(data, start);
    var tableVersion = p.parseVersion(1);
    check.argument(tableVersion === 1 || tableVersion === 1.1, "Unsupported GSUB table version.");
    if (tableVersion === 1) {
      return {
        version: tableVersion,
        scripts: p.parseScriptList(),
        features: p.parseFeatureList(),
        lookups: p.parseLookupList(subtableParsers)
      };
    } else {
      return {
        version: tableVersion,
        scripts: p.parseScriptList(),
        features: p.parseFeatureList(),
        lookups: p.parseLookupList(subtableParsers),
        variations: p.parseFeatureVariationsList()
      };
    }
  }
  var subtableMakers = new Array(9);
  subtableMakers[1] = function makeLookup1(subtable) {
    if (subtable.substFormat === 1) {
      return new table.Table("substitutionTable", [
        { name: "substFormat", type: "USHORT", value: 1 },
        { name: "coverage", type: "TABLE", value: new table.Coverage(subtable.coverage) },
        { name: "deltaGlyphID", type: "USHORT", value: subtable.deltaGlyphId }
      ]);
    } else {
      return new table.Table("substitutionTable", [
        { name: "substFormat", type: "USHORT", value: 2 },
        { name: "coverage", type: "TABLE", value: new table.Coverage(subtable.coverage) }
      ].concat(table.ushortList("substitute", subtable.substitute)));
    }
  };
  subtableMakers[2] = function makeLookup2(subtable) {
    check.assert(subtable.substFormat === 1, "Lookup type 2 substFormat must be 1.");
    return new table.Table("substitutionTable", [
      { name: "substFormat", type: "USHORT", value: 1 },
      { name: "coverage", type: "TABLE", value: new table.Coverage(subtable.coverage) }
    ].concat(table.tableList("seqSet", subtable.sequences, function(sequenceSet) {
      return new table.Table("sequenceSetTable", table.ushortList("sequence", sequenceSet));
    })));
  };
  subtableMakers[3] = function makeLookup3(subtable) {
    check.assert(subtable.substFormat === 1, "Lookup type 3 substFormat must be 1.");
    return new table.Table("substitutionTable", [
      { name: "substFormat", type: "USHORT", value: 1 },
      { name: "coverage", type: "TABLE", value: new table.Coverage(subtable.coverage) }
    ].concat(table.tableList("altSet", subtable.alternateSets, function(alternateSet) {
      return new table.Table("alternateSetTable", table.ushortList("alternate", alternateSet));
    })));
  };
  subtableMakers[4] = function makeLookup4(subtable) {
    check.assert(subtable.substFormat === 1, "Lookup type 4 substFormat must be 1.");
    return new table.Table("substitutionTable", [
      { name: "substFormat", type: "USHORT", value: 1 },
      { name: "coverage", type: "TABLE", value: new table.Coverage(subtable.coverage) }
    ].concat(table.tableList("ligSet", subtable.ligatureSets, function(ligatureSet) {
      return new table.Table("ligatureSetTable", table.tableList("ligature", ligatureSet, function(ligature) {
        return new table.Table(
          "ligatureTable",
          [{ name: "ligGlyph", type: "USHORT", value: ligature.ligGlyph }].concat(table.ushortList("component", ligature.components, ligature.components.length + 1))
        );
      }));
    })));
  };
  subtableMakers[6] = function makeLookup6(subtable) {
    if (subtable.substFormat === 1) {
      var returnTable = new table.Table("chainContextTable", [
        { name: "substFormat", type: "USHORT", value: subtable.substFormat },
        { name: "coverage", type: "TABLE", value: new table.Coverage(subtable.coverage) }
      ].concat(table.tableList("chainRuleSet", subtable.chainRuleSets, function(chainRuleSet) {
        return new table.Table("chainRuleSetTable", table.tableList("chainRule", chainRuleSet, function(chainRule) {
          var tableData2 = table.ushortList("backtrackGlyph", chainRule.backtrack, chainRule.backtrack.length).concat(table.ushortList("inputGlyph", chainRule.input, chainRule.input.length + 1)).concat(table.ushortList("lookaheadGlyph", chainRule.lookahead, chainRule.lookahead.length)).concat(table.ushortList("substitution", [], chainRule.lookupRecords.length));
          chainRule.lookupRecords.forEach(function(record, i) {
            tableData2 = tableData2.concat({ name: "sequenceIndex" + i, type: "USHORT", value: record.sequenceIndex }).concat({ name: "lookupListIndex" + i, type: "USHORT", value: record.lookupListIndex });
          });
          return new table.Table("chainRuleTable", tableData2);
        }));
      })));
      return returnTable;
    } else if (subtable.substFormat === 2) {
      check.assert(false, "lookup type 6 format 2 is not yet supported.");
    } else if (subtable.substFormat === 3) {
      var tableData = [
        { name: "substFormat", type: "USHORT", value: subtable.substFormat }
      ];
      tableData.push({ name: "backtrackGlyphCount", type: "USHORT", value: subtable.backtrackCoverage.length });
      subtable.backtrackCoverage.forEach(function(coverage, i) {
        tableData.push({ name: "backtrackCoverage" + i, type: "TABLE", value: new table.Coverage(coverage) });
      });
      tableData.push({ name: "inputGlyphCount", type: "USHORT", value: subtable.inputCoverage.length });
      subtable.inputCoverage.forEach(function(coverage, i) {
        tableData.push({ name: "inputCoverage" + i, type: "TABLE", value: new table.Coverage(coverage) });
      });
      tableData.push({ name: "lookaheadGlyphCount", type: "USHORT", value: subtable.lookaheadCoverage.length });
      subtable.lookaheadCoverage.forEach(function(coverage, i) {
        tableData.push({ name: "lookaheadCoverage" + i, type: "TABLE", value: new table.Coverage(coverage) });
      });
      tableData.push({ name: "substitutionCount", type: "USHORT", value: subtable.lookupRecords.length });
      subtable.lookupRecords.forEach(function(record, i) {
        tableData = tableData.concat({ name: "sequenceIndex" + i, type: "USHORT", value: record.sequenceIndex }).concat({ name: "lookupListIndex" + i, type: "USHORT", value: record.lookupListIndex });
      });
      var returnTable$1 = new table.Table("chainContextTable", tableData);
      return returnTable$1;
    }
    check.assert(false, "lookup type 6 format must be 1, 2 or 3.");
  };
  function makeGsubTable(gsub2) {
    return new table.Table("GSUB", [
      { name: "version", type: "ULONG", value: 65536 },
      { name: "scripts", type: "TABLE", value: new table.ScriptList(gsub2.scripts) },
      { name: "features", type: "TABLE", value: new table.FeatureList(gsub2.features) },
      { name: "lookups", type: "TABLE", value: new table.LookupList(gsub2.lookups, subtableMakers) }
    ]);
  }
  var gsub = { parse: parseGsubTable, make: makeGsubTable };
  function parseMetaTable(data, start) {
    var p = new parse.Parser(data, start);
    var tableVersion = p.parseULong();
    check.argument(tableVersion === 1, "Unsupported META table version.");
    p.parseULong();
    p.parseULong();
    var numDataMaps = p.parseULong();
    var tags = {};
    for (var i = 0; i < numDataMaps; i++) {
      var tag = p.parseTag();
      var dataOffset = p.parseULong();
      var dataLength = p.parseULong();
      var text = decode.UTF8(data, start + dataOffset, dataLength);
      tags[tag] = text;
    }
    return tags;
  }
  function makeMetaTable(tags) {
    var numTags = Object.keys(tags).length;
    var stringPool = "";
    var stringPoolOffset = 16 + numTags * 12;
    var result = new table.Table("meta", [
      { name: "version", type: "ULONG", value: 1 },
      { name: "flags", type: "ULONG", value: 0 },
      { name: "offset", type: "ULONG", value: stringPoolOffset },
      { name: "numTags", type: "ULONG", value: numTags }
    ]);
    for (var tag in tags) {
      var pos = stringPool.length;
      stringPool += tags[tag];
      result.fields.push({ name: "tag " + tag, type: "TAG", value: tag });
      result.fields.push({ name: "offset " + tag, type: "ULONG", value: stringPoolOffset + pos });
      result.fields.push({ name: "length " + tag, type: "ULONG", value: tags[tag].length });
    }
    result.fields.push({ name: "stringPool", type: "CHARARRAY", value: stringPool });
    return result;
  }
  var meta = { parse: parseMetaTable, make: makeMetaTable };
  function log2(v) {
    return Math.log(v) / Math.log(2) | 0;
  }
  function computeCheckSum(bytes) {
    while (bytes.length % 4 !== 0) {
      bytes.push(0);
    }
    var sum = 0;
    for (var i = 0; i < bytes.length; i += 4) {
      sum += (bytes[i] << 24) + (bytes[i + 1] << 16) + (bytes[i + 2] << 8) + bytes[i + 3];
    }
    sum %= Math.pow(2, 32);
    return sum;
  }
  function makeTableRecord(tag, checkSum, offset, length) {
    return new table.Record("Table Record", [
      { name: "tag", type: "TAG", value: tag !== void 0 ? tag : "" },
      { name: "checkSum", type: "ULONG", value: checkSum !== void 0 ? checkSum : 0 },
      { name: "offset", type: "ULONG", value: offset !== void 0 ? offset : 0 },
      { name: "length", type: "ULONG", value: length !== void 0 ? length : 0 }
    ]);
  }
  function makeSfntTable(tables) {
    var sfnt2 = new table.Table("sfnt", [
      { name: "version", type: "TAG", value: "OTTO" },
      { name: "numTables", type: "USHORT", value: 0 },
      { name: "searchRange", type: "USHORT", value: 0 },
      { name: "entrySelector", type: "USHORT", value: 0 },
      { name: "rangeShift", type: "USHORT", value: 0 }
    ]);
    sfnt2.tables = tables;
    sfnt2.numTables = tables.length;
    var highestPowerOf2 = Math.pow(2, log2(sfnt2.numTables));
    sfnt2.searchRange = 16 * highestPowerOf2;
    sfnt2.entrySelector = log2(highestPowerOf2);
    sfnt2.rangeShift = sfnt2.numTables * 16 - sfnt2.searchRange;
    var recordFields = [];
    var tableFields = [];
    var offset = sfnt2.sizeOf() + makeTableRecord().sizeOf() * sfnt2.numTables;
    while (offset % 4 !== 0) {
      offset += 1;
      tableFields.push({ name: "padding", type: "BYTE", value: 0 });
    }
    for (var i = 0; i < tables.length; i += 1) {
      var t = tables[i];
      check.argument(t.tableName.length === 4, "Table name" + t.tableName + " is invalid.");
      var tableLength = t.sizeOf();
      var tableRecord = makeTableRecord(t.tableName, computeCheckSum(t.encode()), offset, tableLength);
      recordFields.push({ name: tableRecord.tag + " Table Record", type: "RECORD", value: tableRecord });
      tableFields.push({ name: t.tableName + " table", type: "RECORD", value: t });
      offset += tableLength;
      check.argument(!isNaN(offset), "Something went wrong calculating the offset.");
      while (offset % 4 !== 0) {
        offset += 1;
        tableFields.push({ name: "padding", type: "BYTE", value: 0 });
      }
    }
    recordFields.sort(function(r1, r2) {
      if (r1.value.tag > r2.value.tag) {
        return 1;
      } else {
        return -1;
      }
    });
    sfnt2.fields = sfnt2.fields.concat(recordFields);
    sfnt2.fields = sfnt2.fields.concat(tableFields);
    return sfnt2;
  }
  function metricsForChar(font, chars, notFoundMetrics) {
    for (var i = 0; i < chars.length; i += 1) {
      var glyphIndex = font.charToGlyphIndex(chars[i]);
      if (glyphIndex > 0) {
        var glyph = font.glyphs.get(glyphIndex);
        return glyph.getMetrics();
      }
    }
    return notFoundMetrics;
  }
  function average(vs) {
    var sum = 0;
    for (var i = 0; i < vs.length; i += 1) {
      sum += vs[i];
    }
    return sum / vs.length;
  }
  function fontToSfntTable(font) {
    var xMins = [];
    var yMins = [];
    var xMaxs = [];
    var yMaxs = [];
    var advanceWidths = [];
    var leftSideBearings = [];
    var rightSideBearings = [];
    var firstCharIndex;
    var lastCharIndex = 0;
    var ulUnicodeRange1 = 0;
    var ulUnicodeRange2 = 0;
    var ulUnicodeRange3 = 0;
    var ulUnicodeRange4 = 0;
    for (var i = 0; i < font.glyphs.length; i += 1) {
      var glyph = font.glyphs.get(i);
      var unicode = glyph.unicode | 0;
      if (isNaN(glyph.advanceWidth)) {
        throw new Error("Glyph " + glyph.name + " (" + i + "): advanceWidth is not a number.");
      }
      if (firstCharIndex > unicode || firstCharIndex === void 0) {
        if (unicode > 0) {
          firstCharIndex = unicode;
        }
      }
      if (lastCharIndex < unicode) {
        lastCharIndex = unicode;
      }
      var position = os2.getUnicodeRange(unicode);
      if (position < 32) {
        ulUnicodeRange1 |= 1 << position;
      } else if (position < 64) {
        ulUnicodeRange2 |= 1 << position - 32;
      } else if (position < 96) {
        ulUnicodeRange3 |= 1 << position - 64;
      } else if (position < 123) {
        ulUnicodeRange4 |= 1 << position - 96;
      } else {
        throw new Error("Unicode ranges bits > 123 are reserved for internal usage");
      }
      if (glyph.name === ".notdef") {
        continue;
      }
      var metrics = glyph.getMetrics();
      xMins.push(metrics.xMin);
      yMins.push(metrics.yMin);
      xMaxs.push(metrics.xMax);
      yMaxs.push(metrics.yMax);
      leftSideBearings.push(metrics.leftSideBearing);
      rightSideBearings.push(metrics.rightSideBearing);
      advanceWidths.push(glyph.advanceWidth);
    }
    var globals = {
      xMin: Math.min.apply(null, xMins),
      yMin: Math.min.apply(null, yMins),
      xMax: Math.max.apply(null, xMaxs),
      yMax: Math.max.apply(null, yMaxs),
      advanceWidthMax: Math.max.apply(null, advanceWidths),
      advanceWidthAvg: average(advanceWidths),
      minLeftSideBearing: Math.min.apply(null, leftSideBearings),
      maxLeftSideBearing: Math.max.apply(null, leftSideBearings),
      minRightSideBearing: Math.min.apply(null, rightSideBearings)
    };
    globals.ascender = font.ascender;
    globals.descender = font.descender;
    var headTable = head.make({
      flags: 3,
      // 00000011 (baseline for font at y=0; left sidebearing point at x=0)
      unitsPerEm: font.unitsPerEm,
      xMin: globals.xMin,
      yMin: globals.yMin,
      xMax: globals.xMax,
      yMax: globals.yMax,
      lowestRecPPEM: 3,
      createdTimestamp: font.createdTimestamp
    });
    var hheaTable = hhea.make({
      ascender: globals.ascender,
      descender: globals.descender,
      advanceWidthMax: globals.advanceWidthMax,
      minLeftSideBearing: globals.minLeftSideBearing,
      minRightSideBearing: globals.minRightSideBearing,
      xMaxExtent: globals.maxLeftSideBearing + (globals.xMax - globals.xMin),
      numberOfHMetrics: font.glyphs.length
    });
    var maxpTable = maxp.make(font.glyphs.length);
    var os2Table = os2.make(Object.assign({
      xAvgCharWidth: Math.round(globals.advanceWidthAvg),
      usFirstCharIndex: firstCharIndex,
      usLastCharIndex: lastCharIndex,
      ulUnicodeRange1,
      ulUnicodeRange2,
      ulUnicodeRange3,
      ulUnicodeRange4,
      // See http://typophile.com/node/13081 for more info on vertical metrics.
      // We get metrics for typical characters (such as "x" for xHeight).
      // We provide some fallback characters if characters are unavailable: their
      // ordering was chosen experimentally.
      sTypoAscender: globals.ascender,
      sTypoDescender: globals.descender,
      sTypoLineGap: 0,
      usWinAscent: globals.yMax,
      usWinDescent: Math.abs(globals.yMin),
      ulCodePageRange1: 1,
      // FIXME: hard-code Latin 1 support for now
      sxHeight: metricsForChar(font, "xyvw", { yMax: Math.round(globals.ascender / 2) }).yMax,
      sCapHeight: metricsForChar(font, "HIKLEFJMNTZBDPRAGOQSUVWXY", globals).yMax,
      usDefaultChar: font.hasChar(" ") ? 32 : 0,
      // Use space as the default character, if available.
      usBreakChar: font.hasChar(" ") ? 32 : 0
      // Use space as the break character, if available.
    }, font.tables.os2));
    var hmtxTable = hmtx.make(font.glyphs);
    var cmapTable = cmap.make(font.glyphs);
    var englishFamilyName = font.getEnglishName("fontFamily");
    var englishStyleName = font.getEnglishName("fontSubfamily");
    var englishFullName = englishFamilyName + " " + englishStyleName;
    var postScriptName = font.getEnglishName("postScriptName");
    if (!postScriptName) {
      postScriptName = englishFamilyName.replace(/\s/g, "") + "-" + englishStyleName;
    }
    var names = {};
    for (var n in font.names) {
      names[n] = font.names[n];
    }
    if (!names.uniqueID) {
      names.uniqueID = { en: font.getEnglishName("manufacturer") + ":" + englishFullName };
    }
    if (!names.postScriptName) {
      names.postScriptName = { en: postScriptName };
    }
    if (!names.preferredFamily) {
      names.preferredFamily = font.names.fontFamily;
    }
    if (!names.preferredSubfamily) {
      names.preferredSubfamily = font.names.fontSubfamily;
    }
    var languageTags = [];
    var nameTable = _name.make(names, languageTags);
    var ltagTable = languageTags.length > 0 ? ltag.make(languageTags) : void 0;
    var postTable = post.make();
    var cffTable = cff.make(font.glyphs, {
      version: font.getEnglishName("version"),
      fullName: englishFullName,
      familyName: englishFamilyName,
      weightName: englishStyleName,
      postScriptName,
      unitsPerEm: font.unitsPerEm,
      fontBBox: [0, globals.yMin, globals.ascender, globals.advanceWidthMax]
    });
    var metaTable = font.metas && Object.keys(font.metas).length > 0 ? meta.make(font.metas) : void 0;
    var tables = [headTable, hheaTable, maxpTable, os2Table, nameTable, cmapTable, postTable, cffTable, hmtxTable];
    if (ltagTable) {
      tables.push(ltagTable);
    }
    if (font.tables.gsub) {
      tables.push(gsub.make(font.tables.gsub));
    }
    if (metaTable) {
      tables.push(metaTable);
    }
    var sfntTable = makeSfntTable(tables);
    var bytes = sfntTable.encode();
    var checkSum = computeCheckSum(bytes);
    var tableFields = sfntTable.fields;
    var checkSumAdjusted = false;
    for (var i$1 = 0; i$1 < tableFields.length; i$1 += 1) {
      if (tableFields[i$1].name === "head table") {
        tableFields[i$1].value.checkSumAdjustment = 2981146554 - checkSum;
        checkSumAdjusted = true;
        break;
      }
    }
    if (!checkSumAdjusted) {
      throw new Error("Could not find head table with checkSum to adjust.");
    }
    return sfntTable;
  }
  var sfnt = { make: makeSfntTable, fontToTable: fontToSfntTable, computeCheckSum };
  function searchTag(arr, tag) {
    var imin = 0;
    var imax = arr.length - 1;
    while (imin <= imax) {
      var imid = imin + imax >>> 1;
      var val = arr[imid].tag;
      if (val === tag) {
        return imid;
      } else if (val < tag) {
        imin = imid + 1;
      } else {
        imax = imid - 1;
      }
    }
    return -imin - 1;
  }
  function binSearch(arr, value) {
    var imin = 0;
    var imax = arr.length - 1;
    while (imin <= imax) {
      var imid = imin + imax >>> 1;
      var val = arr[imid];
      if (val === value) {
        return imid;
      } else if (val < value) {
        imin = imid + 1;
      } else {
        imax = imid - 1;
      }
    }
    return -imin - 1;
  }
  function searchRange(ranges, value) {
    var range;
    var imin = 0;
    var imax = ranges.length - 1;
    while (imin <= imax) {
      var imid = imin + imax >>> 1;
      range = ranges[imid];
      var start = range.start;
      if (start === value) {
        return range;
      } else if (start < value) {
        imin = imid + 1;
      } else {
        imax = imid - 1;
      }
    }
    if (imin > 0) {
      range = ranges[imin - 1];
      if (value > range.end) {
        return 0;
      }
      return range;
    }
  }
  function Layout(font, tableName) {
    this.font = font;
    this.tableName = tableName;
  }
  Layout.prototype = {
    /**
     * Binary search an object by "tag" property
     * @instance
     * @function searchTag
     * @memberof opentype.Layout
     * @param  {Array} arr
     * @param  {string} tag
     * @return {number}
     */
    searchTag,
    /**
     * Binary search in a list of numbers
     * @instance
     * @function binSearch
     * @memberof opentype.Layout
     * @param  {Array} arr
     * @param  {number} value
     * @return {number}
     */
    binSearch,
    /**
     * Get or create the Layout table (GSUB, GPOS etc).
     * @param  {boolean} create - Whether to create a new one.
     * @return {Object} The GSUB or GPOS table.
     */
    getTable: function(create) {
      var layout = this.font.tables[this.tableName];
      if (!layout && create) {
        layout = this.font.tables[this.tableName] = this.createDefaultTable();
      }
      return layout;
    },
    /**
     * Returns all scripts in the substitution table.
     * @instance
     * @return {Array}
     */
    getScriptNames: function() {
      var layout = this.getTable();
      if (!layout) {
        return [];
      }
      return layout.scripts.map(function(script) {
        return script.tag;
      });
    },
    /**
     * Returns the best bet for a script name.
     * Returns 'DFLT' if it exists.
     * If not, returns 'latn' if it exists.
     * If neither exist, returns undefined.
     */
    getDefaultScriptName: function() {
      var layout = this.getTable();
      if (!layout) {
        return;
      }
      var hasLatn = false;
      for (var i = 0; i < layout.scripts.length; i++) {
        var name = layout.scripts[i].tag;
        if (name === "DFLT") {
          return name;
        }
        if (name === "latn") {
          hasLatn = true;
        }
      }
      if (hasLatn) {
        return "latn";
      }
    },
    /**
     * Returns all LangSysRecords in the given script.
     * @instance
     * @param {string} [script='DFLT']
     * @param {boolean} create - forces the creation of this script table if it doesn't exist.
     * @return {Object} An object with tag and script properties.
     */
    getScriptTable: function(script, create) {
      var layout = this.getTable(create);
      if (layout) {
        script = script || "DFLT";
        var scripts = layout.scripts;
        var pos = searchTag(layout.scripts, script);
        if (pos >= 0) {
          return scripts[pos].script;
        } else if (create) {
          var scr = {
            tag: script,
            script: {
              defaultLangSys: { reserved: 0, reqFeatureIndex: 65535, featureIndexes: [] },
              langSysRecords: []
            }
          };
          scripts.splice(-1 - pos, 0, scr);
          return scr.script;
        }
      }
    },
    /**
     * Returns a language system table
     * @instance
     * @param {string} [script='DFLT']
     * @param {string} [language='dlft']
     * @param {boolean} create - forces the creation of this langSysTable if it doesn't exist.
     * @return {Object}
     */
    getLangSysTable: function(script, language, create) {
      var scriptTable = this.getScriptTable(script, create);
      if (scriptTable) {
        if (!language || language === "dflt" || language === "DFLT") {
          return scriptTable.defaultLangSys;
        }
        var pos = searchTag(scriptTable.langSysRecords, language);
        if (pos >= 0) {
          return scriptTable.langSysRecords[pos].langSys;
        } else if (create) {
          var langSysRecord = {
            tag: language,
            langSys: { reserved: 0, reqFeatureIndex: 65535, featureIndexes: [] }
          };
          scriptTable.langSysRecords.splice(-1 - pos, 0, langSysRecord);
          return langSysRecord.langSys;
        }
      }
    },
    /**
     * Get a specific feature table.
     * @instance
     * @param {string} [script='DFLT']
     * @param {string} [language='dlft']
     * @param {string} feature - One of the codes listed at https://www.microsoft.com/typography/OTSPEC/featurelist.htm
     * @param {boolean} create - forces the creation of the feature table if it doesn't exist.
     * @return {Object}
     */
    getFeatureTable: function(script, language, feature, create) {
      var langSysTable2 = this.getLangSysTable(script, language, create);
      if (langSysTable2) {
        var featureRecord;
        var featIndexes = langSysTable2.featureIndexes;
        var allFeatures = this.font.tables[this.tableName].features;
        for (var i = 0; i < featIndexes.length; i++) {
          featureRecord = allFeatures[featIndexes[i]];
          if (featureRecord.tag === feature) {
            return featureRecord.feature;
          }
        }
        if (create) {
          var index = allFeatures.length;
          check.assert(index === 0 || feature >= allFeatures[index - 1].tag, "Features must be added in alphabetical order.");
          featureRecord = {
            tag: feature,
            feature: { params: 0, lookupListIndexes: [] }
          };
          allFeatures.push(featureRecord);
          featIndexes.push(index);
          return featureRecord.feature;
        }
      }
    },
    /**
     * Get the lookup tables of a given type for a script/language/feature.
     * @instance
     * @param {string} [script='DFLT']
     * @param {string} [language='dlft']
     * @param {string} feature - 4-letter feature code
     * @param {number} lookupType - 1 to 9
     * @param {boolean} create - forces the creation of the lookup table if it doesn't exist, with no subtables.
     * @return {Object[]}
     */
    getLookupTables: function(script, language, feature, lookupType, create) {
      var featureTable = this.getFeatureTable(script, language, feature, create);
      var tables = [];
      if (featureTable) {
        var lookupTable;
        var lookupListIndexes = featureTable.lookupListIndexes;
        var allLookups = this.font.tables[this.tableName].lookups;
        for (var i = 0; i < lookupListIndexes.length; i++) {
          lookupTable = allLookups[lookupListIndexes[i]];
          if (lookupTable.lookupType === lookupType) {
            tables.push(lookupTable);
          }
        }
        if (tables.length === 0 && create) {
          lookupTable = {
            lookupType,
            lookupFlag: 0,
            subtables: [],
            markFilteringSet: void 0
          };
          var index = allLookups.length;
          allLookups.push(lookupTable);
          lookupListIndexes.push(index);
          return [lookupTable];
        }
      }
      return tables;
    },
    /**
     * Find a glyph in a class definition table
     * https://docs.microsoft.com/en-us/typography/opentype/spec/chapter2#class-definition-table
     * @param {object} classDefTable - an OpenType Layout class definition table
     * @param {number} glyphIndex - the index of the glyph to find
     * @returns {number} -1 if not found
     */
    getGlyphClass: function(classDefTable, glyphIndex) {
      switch (classDefTable.format) {
        case 1:
          if (classDefTable.startGlyph <= glyphIndex && glyphIndex < classDefTable.startGlyph + classDefTable.classes.length) {
            return classDefTable.classes[glyphIndex - classDefTable.startGlyph];
          }
          return 0;
        case 2:
          var range = searchRange(classDefTable.ranges, glyphIndex);
          return range ? range.classId : 0;
      }
    },
    /**
     * Find a glyph in a coverage table
     * https://docs.microsoft.com/en-us/typography/opentype/spec/chapter2#coverage-table
     * @param {object} coverageTable - an OpenType Layout coverage table
     * @param {number} glyphIndex - the index of the glyph to find
     * @returns {number} -1 if not found
     */
    getCoverageIndex: function(coverageTable, glyphIndex) {
      switch (coverageTable.format) {
        case 1:
          var index = binSearch(coverageTable.glyphs, glyphIndex);
          return index >= 0 ? index : -1;
        case 2:
          var range = searchRange(coverageTable.ranges, glyphIndex);
          return range ? range.index + glyphIndex - range.start : -1;
      }
    },
    /**
     * Returns the list of glyph indexes of a coverage table.
     * Format 1: the list is stored raw
     * Format 2: compact list as range records.
     * @instance
     * @param  {Object} coverageTable
     * @return {Array}
     */
    expandCoverage: function(coverageTable) {
      if (coverageTable.format === 1) {
        return coverageTable.glyphs;
      } else {
        var glyphs = [];
        var ranges = coverageTable.ranges;
        for (var i = 0; i < ranges.length; i++) {
          var range = ranges[i];
          var start = range.start;
          var end = range.end;
          for (var j = start; j <= end; j++) {
            glyphs.push(j);
          }
        }
        return glyphs;
      }
    }
  };
  function Position(font) {
    Layout.call(this, font, "gpos");
  }
  Position.prototype = Layout.prototype;
  Position.prototype.init = function() {
    var script = this.getDefaultScriptName();
    this.defaultKerningTables = this.getKerningTables(script);
  };
  Position.prototype.getKerningValue = function(kerningLookups, leftIndex, rightIndex) {
    for (var i = 0; i < kerningLookups.length; i++) {
      var subtables = kerningLookups[i].subtables;
      for (var j = 0; j < subtables.length; j++) {
        var subtable = subtables[j];
        var covIndex = this.getCoverageIndex(subtable.coverage, leftIndex);
        if (covIndex < 0) {
          continue;
        }
        switch (subtable.posFormat) {
          case 1:
            var pairSet = subtable.pairSets[covIndex];
            for (var k = 0; k < pairSet.length; k++) {
              var pair = pairSet[k];
              if (pair.secondGlyph === rightIndex) {
                return pair.value1 && pair.value1.xAdvance || 0;
              }
            }
            break;
          case 2:
            var class1 = this.getGlyphClass(subtable.classDef1, leftIndex);
            var class2 = this.getGlyphClass(subtable.classDef2, rightIndex);
            var pair$1 = subtable.classRecords[class1][class2];
            return pair$1.value1 && pair$1.value1.xAdvance || 0;
        }
      }
    }
    return 0;
  };
  Position.prototype.getKerningTables = function(script, language) {
    if (this.font.tables.gpos) {
      return this.getLookupTables(script, language, "kern", 2);
    }
  };
  function Substitution(font) {
    Layout.call(this, font, "gsub");
  }
  function arraysEqual(ar1, ar2) {
    var n = ar1.length;
    if (n !== ar2.length) {
      return false;
    }
    for (var i = 0; i < n; i++) {
      if (ar1[i] !== ar2[i]) {
        return false;
      }
    }
    return true;
  }
  function getSubstFormat(lookupTable, format, defaultSubtable) {
    var subtables = lookupTable.subtables;
    for (var i = 0; i < subtables.length; i++) {
      var subtable = subtables[i];
      if (subtable.substFormat === format) {
        return subtable;
      }
    }
    if (defaultSubtable) {
      subtables.push(defaultSubtable);
      return defaultSubtable;
    }
    return void 0;
  }
  Substitution.prototype = Layout.prototype;
  Substitution.prototype.createDefaultTable = function() {
    return {
      version: 1,
      scripts: [{
        tag: "DFLT",
        script: {
          defaultLangSys: { reserved: 0, reqFeatureIndex: 65535, featureIndexes: [] },
          langSysRecords: []
        }
      }],
      features: [],
      lookups: []
    };
  };
  Substitution.prototype.getSingle = function(feature, script, language) {
    var substitutions = [];
    var lookupTables = this.getLookupTables(script, language, feature, 1);
    for (var idx = 0; idx < lookupTables.length; idx++) {
      var subtables = lookupTables[idx].subtables;
      for (var i = 0; i < subtables.length; i++) {
        var subtable = subtables[i];
        var glyphs = this.expandCoverage(subtable.coverage);
        var j = void 0;
        if (subtable.substFormat === 1) {
          var delta = subtable.deltaGlyphId;
          for (j = 0; j < glyphs.length; j++) {
            var glyph = glyphs[j];
            substitutions.push({ sub: glyph, by: glyph + delta });
          }
        } else {
          var substitute = subtable.substitute;
          for (j = 0; j < glyphs.length; j++) {
            substitutions.push({ sub: glyphs[j], by: substitute[j] });
          }
        }
      }
    }
    return substitutions;
  };
  Substitution.prototype.getMultiple = function(feature, script, language) {
    var substitutions = [];
    var lookupTables = this.getLookupTables(script, language, feature, 2);
    for (var idx = 0; idx < lookupTables.length; idx++) {
      var subtables = lookupTables[idx].subtables;
      for (var i = 0; i < subtables.length; i++) {
        var subtable = subtables[i];
        var glyphs = this.expandCoverage(subtable.coverage);
        var j = void 0;
        for (j = 0; j < glyphs.length; j++) {
          var glyph = glyphs[j];
          var replacements = subtable.sequences[j];
          substitutions.push({ sub: glyph, by: replacements });
        }
      }
    }
    return substitutions;
  };
  Substitution.prototype.getAlternates = function(feature, script, language) {
    var alternates = [];
    var lookupTables = this.getLookupTables(script, language, feature, 3);
    for (var idx = 0; idx < lookupTables.length; idx++) {
      var subtables = lookupTables[idx].subtables;
      for (var i = 0; i < subtables.length; i++) {
        var subtable = subtables[i];
        var glyphs = this.expandCoverage(subtable.coverage);
        var alternateSets = subtable.alternateSets;
        for (var j = 0; j < glyphs.length; j++) {
          alternates.push({ sub: glyphs[j], by: alternateSets[j] });
        }
      }
    }
    return alternates;
  };
  Substitution.prototype.getLigatures = function(feature, script, language) {
    var ligatures = [];
    var lookupTables = this.getLookupTables(script, language, feature, 4);
    for (var idx = 0; idx < lookupTables.length; idx++) {
      var subtables = lookupTables[idx].subtables;
      for (var i = 0; i < subtables.length; i++) {
        var subtable = subtables[i];
        var glyphs = this.expandCoverage(subtable.coverage);
        var ligatureSets = subtable.ligatureSets;
        for (var j = 0; j < glyphs.length; j++) {
          var startGlyph = glyphs[j];
          var ligSet = ligatureSets[j];
          for (var k = 0; k < ligSet.length; k++) {
            var lig = ligSet[k];
            ligatures.push({
              sub: [startGlyph].concat(lig.components),
              by: lig.ligGlyph
            });
          }
        }
      }
    }
    return ligatures;
  };
  Substitution.prototype.addSingle = function(feature, substitution, script, language) {
    var lookupTable = this.getLookupTables(script, language, feature, 1, true)[0];
    var subtable = getSubstFormat(lookupTable, 2, {
      // lookup type 1 subtable, format 2, coverage format 1
      substFormat: 2,
      coverage: { format: 1, glyphs: [] },
      substitute: []
    });
    check.assert(subtable.coverage.format === 1, "Single: unable to modify coverage table format " + subtable.coverage.format);
    var coverageGlyph = substitution.sub;
    var pos = this.binSearch(subtable.coverage.glyphs, coverageGlyph);
    if (pos < 0) {
      pos = -1 - pos;
      subtable.coverage.glyphs.splice(pos, 0, coverageGlyph);
      subtable.substitute.splice(pos, 0, 0);
    }
    subtable.substitute[pos] = substitution.by;
  };
  Substitution.prototype.addMultiple = function(feature, substitution, script, language) {
    check.assert(substitution.by instanceof Array && substitution.by.length > 1, 'Multiple: "by" must be an array of two or more ids');
    var lookupTable = this.getLookupTables(script, language, feature, 2, true)[0];
    var subtable = getSubstFormat(lookupTable, 1, {
      // lookup type 2 subtable, format 1, coverage format 1
      substFormat: 1,
      coverage: { format: 1, glyphs: [] },
      sequences: []
    });
    check.assert(subtable.coverage.format === 1, "Multiple: unable to modify coverage table format " + subtable.coverage.format);
    var coverageGlyph = substitution.sub;
    var pos = this.binSearch(subtable.coverage.glyphs, coverageGlyph);
    if (pos < 0) {
      pos = -1 - pos;
      subtable.coverage.glyphs.splice(pos, 0, coverageGlyph);
      subtable.sequences.splice(pos, 0, 0);
    }
    subtable.sequences[pos] = substitution.by;
  };
  Substitution.prototype.addAlternate = function(feature, substitution, script, language) {
    var lookupTable = this.getLookupTables(script, language, feature, 3, true)[0];
    var subtable = getSubstFormat(lookupTable, 1, {
      // lookup type 3 subtable, format 1, coverage format 1
      substFormat: 1,
      coverage: { format: 1, glyphs: [] },
      alternateSets: []
    });
    check.assert(subtable.coverage.format === 1, "Alternate: unable to modify coverage table format " + subtable.coverage.format);
    var coverageGlyph = substitution.sub;
    var pos = this.binSearch(subtable.coverage.glyphs, coverageGlyph);
    if (pos < 0) {
      pos = -1 - pos;
      subtable.coverage.glyphs.splice(pos, 0, coverageGlyph);
      subtable.alternateSets.splice(pos, 0, 0);
    }
    subtable.alternateSets[pos] = substitution.by;
  };
  Substitution.prototype.addLigature = function(feature, ligature, script, language) {
    var lookupTable = this.getLookupTables(script, language, feature, 4, true)[0];
    var subtable = lookupTable.subtables[0];
    if (!subtable) {
      subtable = {
        // lookup type 4 subtable, format 1, coverage format 1
        substFormat: 1,
        coverage: { format: 1, glyphs: [] },
        ligatureSets: []
      };
      lookupTable.subtables[0] = subtable;
    }
    check.assert(subtable.coverage.format === 1, "Ligature: unable to modify coverage table format " + subtable.coverage.format);
    var coverageGlyph = ligature.sub[0];
    var ligComponents = ligature.sub.slice(1);
    var ligatureTable = {
      ligGlyph: ligature.by,
      components: ligComponents
    };
    var pos = this.binSearch(subtable.coverage.glyphs, coverageGlyph);
    if (pos >= 0) {
      var ligatureSet = subtable.ligatureSets[pos];
      for (var i = 0; i < ligatureSet.length; i++) {
        if (arraysEqual(ligatureSet[i].components, ligComponents)) {
          return;
        }
      }
      ligatureSet.push(ligatureTable);
    } else {
      pos = -1 - pos;
      subtable.coverage.glyphs.splice(pos, 0, coverageGlyph);
      subtable.ligatureSets.splice(pos, 0, [ligatureTable]);
    }
  };
  Substitution.prototype.getFeature = function(feature, script, language) {
    if (/ss\d\d/.test(feature)) {
      return this.getSingle(feature, script, language);
    }
    switch (feature) {
      case "aalt":
      case "salt":
        return this.getSingle(feature, script, language).concat(this.getAlternates(feature, script, language));
      case "dlig":
      case "liga":
      case "rlig":
        return this.getLigatures(feature, script, language);
      case "ccmp":
        return this.getMultiple(feature, script, language).concat(this.getLigatures(feature, script, language));
      case "stch":
        return this.getMultiple(feature, script, language);
    }
    return void 0;
  };
  Substitution.prototype.add = function(feature, sub, script, language) {
    if (/ss\d\d/.test(feature)) {
      return this.addSingle(feature, sub, script, language);
    }
    switch (feature) {
      case "aalt":
      case "salt":
        if (typeof sub.by === "number") {
          return this.addSingle(feature, sub, script, language);
        }
        return this.addAlternate(feature, sub, script, language);
      case "dlig":
      case "liga":
      case "rlig":
        return this.addLigature(feature, sub, script, language);
      case "ccmp":
        if (sub.by instanceof Array) {
          return this.addMultiple(feature, sub, script, language);
        }
        return this.addLigature(feature, sub, script, language);
    }
    return void 0;
  };
  function isBrowser() {
    return typeof window !== "undefined";
  }
  function nodeBufferToArrayBuffer(buffer) {
    var ab = new ArrayBuffer(buffer.length);
    var view = new Uint8Array(ab);
    for (var i = 0; i < buffer.length; ++i) {
      view[i] = buffer[i];
    }
    return ab;
  }
  function arrayBufferToNodeBuffer(ab) {
    var buffer = new Buffer(ab.byteLength);
    var view = new Uint8Array(ab);
    for (var i = 0; i < buffer.length; ++i) {
      buffer[i] = view[i];
    }
    return buffer;
  }
  function checkArgument(expression, message) {
    if (!expression) {
      throw message;
    }
  }
  function parseGlyphCoordinate(p, flag, previousValue, shortVectorBitMask, sameBitMask) {
    var v;
    if ((flag & shortVectorBitMask) > 0) {
      v = p.parseByte();
      if ((flag & sameBitMask) === 0) {
        v = -v;
      }
      v = previousValue + v;
    } else {
      if ((flag & sameBitMask) > 0) {
        v = previousValue;
      } else {
        v = previousValue + p.parseShort();
      }
    }
    return v;
  }
  function parseGlyph(glyph, data, start) {
    var p = new parse.Parser(data, start);
    glyph.numberOfContours = p.parseShort();
    glyph._xMin = p.parseShort();
    glyph._yMin = p.parseShort();
    glyph._xMax = p.parseShort();
    glyph._yMax = p.parseShort();
    var flags;
    var flag;
    if (glyph.numberOfContours > 0) {
      var endPointIndices = glyph.endPointIndices = [];
      for (var i = 0; i < glyph.numberOfContours; i += 1) {
        endPointIndices.push(p.parseUShort());
      }
      glyph.instructionLength = p.parseUShort();
      glyph.instructions = [];
      for (var i$1 = 0; i$1 < glyph.instructionLength; i$1 += 1) {
        glyph.instructions.push(p.parseByte());
      }
      var numberOfCoordinates = endPointIndices[endPointIndices.length - 1] + 1;
      flags = [];
      for (var i$2 = 0; i$2 < numberOfCoordinates; i$2 += 1) {
        flag = p.parseByte();
        flags.push(flag);
        if ((flag & 8) > 0) {
          var repeatCount = p.parseByte();
          for (var j = 0; j < repeatCount; j += 1) {
            flags.push(flag);
            i$2 += 1;
          }
        }
      }
      check.argument(flags.length === numberOfCoordinates, "Bad flags.");
      if (endPointIndices.length > 0) {
        var points = [];
        var point;
        if (numberOfCoordinates > 0) {
          for (var i$3 = 0; i$3 < numberOfCoordinates; i$3 += 1) {
            flag = flags[i$3];
            point = {};
            point.onCurve = !!(flag & 1);
            point.lastPointOfContour = endPointIndices.indexOf(i$3) >= 0;
            points.push(point);
          }
          var px = 0;
          for (var i$4 = 0; i$4 < numberOfCoordinates; i$4 += 1) {
            flag = flags[i$4];
            point = points[i$4];
            point.x = parseGlyphCoordinate(p, flag, px, 2, 16);
            px = point.x;
          }
          var py = 0;
          for (var i$5 = 0; i$5 < numberOfCoordinates; i$5 += 1) {
            flag = flags[i$5];
            point = points[i$5];
            point.y = parseGlyphCoordinate(p, flag, py, 4, 32);
            py = point.y;
          }
        }
        glyph.points = points;
      } else {
        glyph.points = [];
      }
    } else if (glyph.numberOfContours === 0) {
      glyph.points = [];
    } else {
      glyph.isComposite = true;
      glyph.points = [];
      glyph.components = [];
      var moreComponents = true;
      while (moreComponents) {
        flags = p.parseUShort();
        var component = {
          glyphIndex: p.parseUShort(),
          xScale: 1,
          scale01: 0,
          scale10: 0,
          yScale: 1,
          dx: 0,
          dy: 0
        };
        if ((flags & 1) > 0) {
          if ((flags & 2) > 0) {
            component.dx = p.parseShort();
            component.dy = p.parseShort();
          } else {
            component.matchedPoints = [p.parseUShort(), p.parseUShort()];
          }
        } else {
          if ((flags & 2) > 0) {
            component.dx = p.parseChar();
            component.dy = p.parseChar();
          } else {
            component.matchedPoints = [p.parseByte(), p.parseByte()];
          }
        }
        if ((flags & 8) > 0) {
          component.xScale = component.yScale = p.parseF2Dot14();
        } else if ((flags & 64) > 0) {
          component.xScale = p.parseF2Dot14();
          component.yScale = p.parseF2Dot14();
        } else if ((flags & 128) > 0) {
          component.xScale = p.parseF2Dot14();
          component.scale01 = p.parseF2Dot14();
          component.scale10 = p.parseF2Dot14();
          component.yScale = p.parseF2Dot14();
        }
        glyph.components.push(component);
        moreComponents = !!(flags & 32);
      }
      if (flags & 256) {
        glyph.instructionLength = p.parseUShort();
        glyph.instructions = [];
        for (var i$6 = 0; i$6 < glyph.instructionLength; i$6 += 1) {
          glyph.instructions.push(p.parseByte());
        }
      }
    }
  }
  function transformPoints(points, transform) {
    var newPoints = [];
    for (var i = 0; i < points.length; i += 1) {
      var pt = points[i];
      var newPt = {
        x: transform.xScale * pt.x + transform.scale01 * pt.y + transform.dx,
        y: transform.scale10 * pt.x + transform.yScale * pt.y + transform.dy,
        onCurve: pt.onCurve,
        lastPointOfContour: pt.lastPointOfContour
      };
      newPoints.push(newPt);
    }
    return newPoints;
  }
  function getContours(points) {
    var contours = [];
    var currentContour = [];
    for (var i = 0; i < points.length; i += 1) {
      var pt = points[i];
      currentContour.push(pt);
      if (pt.lastPointOfContour) {
        contours.push(currentContour);
        currentContour = [];
      }
    }
    check.argument(currentContour.length === 0, "There are still points left in the current contour.");
    return contours;
  }
  function getPath(points) {
    var p = new Path();
    if (!points) {
      return p;
    }
    var contours = getContours(points);
    for (var contourIndex = 0; contourIndex < contours.length; ++contourIndex) {
      var contour = contours[contourIndex];
      var prev = null;
      var curr = contour[contour.length - 1];
      var next = contour[0];
      if (curr.onCurve) {
        p.moveTo(curr.x, curr.y);
      } else {
        if (next.onCurve) {
          p.moveTo(next.x, next.y);
        } else {
          var start = { x: (curr.x + next.x) * 0.5, y: (curr.y + next.y) * 0.5 };
          p.moveTo(start.x, start.y);
        }
      }
      for (var i = 0; i < contour.length; ++i) {
        prev = curr;
        curr = next;
        next = contour[(i + 1) % contour.length];
        if (curr.onCurve) {
          p.lineTo(curr.x, curr.y);
        } else {
          var prev2 = prev;
          var next2 = next;
          if (!prev.onCurve) {
            prev2 = { x: (curr.x + prev.x) * 0.5, y: (curr.y + prev.y) * 0.5 };
          }
          if (!next.onCurve) {
            next2 = { x: (curr.x + next.x) * 0.5, y: (curr.y + next.y) * 0.5 };
          }
          p.quadraticCurveTo(curr.x, curr.y, next2.x, next2.y);
        }
      }
      p.closePath();
    }
    return p;
  }
  function buildPath(glyphs, glyph) {
    if (glyph.isComposite) {
      for (var j = 0; j < glyph.components.length; j += 1) {
        var component = glyph.components[j];
        var componentGlyph = glyphs.get(component.glyphIndex);
        componentGlyph.getPath();
        if (componentGlyph.points) {
          var transformedPoints = void 0;
          if (component.matchedPoints === void 0) {
            transformedPoints = transformPoints(componentGlyph.points, component);
          } else {
            if (component.matchedPoints[0] > glyph.points.length - 1 || component.matchedPoints[1] > componentGlyph.points.length - 1) {
              throw Error("Matched points out of range in " + glyph.name);
            }
            var firstPt = glyph.points[component.matchedPoints[0]];
            var secondPt = componentGlyph.points[component.matchedPoints[1]];
            var transform = {
              xScale: component.xScale,
              scale01: component.scale01,
              scale10: component.scale10,
              yScale: component.yScale,
              dx: 0,
              dy: 0
            };
            secondPt = transformPoints([secondPt], transform)[0];
            transform.dx = firstPt.x - secondPt.x;
            transform.dy = firstPt.y - secondPt.y;
            transformedPoints = transformPoints(componentGlyph.points, transform);
          }
          glyph.points = glyph.points.concat(transformedPoints);
        }
      }
    }
    return getPath(glyph.points);
  }
  function parseGlyfTableAll(data, start, loca2, font) {
    var glyphs = new glyphset.GlyphSet(font);
    for (var i = 0; i < loca2.length - 1; i += 1) {
      var offset = loca2[i];
      var nextOffset = loca2[i + 1];
      if (offset !== nextOffset) {
        glyphs.push(i, glyphset.ttfGlyphLoader(font, i, parseGlyph, data, start + offset, buildPath));
      } else {
        glyphs.push(i, glyphset.glyphLoader(font, i));
      }
    }
    return glyphs;
  }
  function parseGlyfTableOnLowMemory(data, start, loca2, font) {
    var glyphs = new glyphset.GlyphSet(font);
    font._push = function(i) {
      var offset = loca2[i];
      var nextOffset = loca2[i + 1];
      if (offset !== nextOffset) {
        glyphs.push(i, glyphset.ttfGlyphLoader(font, i, parseGlyph, data, start + offset, buildPath));
      } else {
        glyphs.push(i, glyphset.glyphLoader(font, i));
      }
    };
    return glyphs;
  }
  function parseGlyfTable(data, start, loca2, font, opt) {
    if (opt.lowMemory) {
      return parseGlyfTableOnLowMemory(data, start, loca2, font);
    } else {
      return parseGlyfTableAll(data, start, loca2, font);
    }
  }
  var glyf = { getPath, parse: parseGlyfTable };
  var instructionTable;
  var exec;
  var execGlyph;
  var execComponent;
  function Hinting(font) {
    this.font = font;
    this.getCommands = function(hPoints) {
      return glyf.getPath(hPoints).commands;
    };
    this._fpgmState = this._prepState = void 0;
    this._errorState = 0;
  }
  function roundOff(v) {
    return v;
  }
  function roundToGrid(v) {
    return Math.sign(v) * Math.round(Math.abs(v));
  }
  function roundToDoubleGrid(v) {
    return Math.sign(v) * Math.round(Math.abs(v * 2)) / 2;
  }
  function roundToHalfGrid(v) {
    return Math.sign(v) * (Math.round(Math.abs(v) + 0.5) - 0.5);
  }
  function roundUpToGrid(v) {
    return Math.sign(v) * Math.ceil(Math.abs(v));
  }
  function roundDownToGrid(v) {
    return Math.sign(v) * Math.floor(Math.abs(v));
  }
  var roundSuper = function(v) {
    var period = this.srPeriod;
    var phase = this.srPhase;
    var threshold = this.srThreshold;
    var sign = 1;
    if (v < 0) {
      v = -v;
      sign = -1;
    }
    v += threshold - phase;
    v = Math.trunc(v / period) * period;
    v += phase;
    if (v < 0) {
      return phase * sign;
    }
    return v * sign;
  };
  var xUnitVector = {
    x: 1,
    y: 0,
    axis: "x",
    // Gets the projected distance between two points.
    // o1/o2 ... if true, respective original position is used.
    distance: function(p1, p2, o1, o2) {
      return (o1 ? p1.xo : p1.x) - (o2 ? p2.xo : p2.x);
    },
    // Moves point p so the moved position has the same relative
    // position to the moved positions of rp1 and rp2 than the
    // original positions had.
    //
    // See APPENDIX on INTERPOLATE at the bottom of this file.
    interpolate: function(p, rp1, rp2, pv) {
      var do1;
      var do2;
      var doa1;
      var doa2;
      var dm1;
      var dm2;
      var dt;
      if (!pv || pv === this) {
        do1 = p.xo - rp1.xo;
        do2 = p.xo - rp2.xo;
        dm1 = rp1.x - rp1.xo;
        dm2 = rp2.x - rp2.xo;
        doa1 = Math.abs(do1);
        doa2 = Math.abs(do2);
        dt = doa1 + doa2;
        if (dt === 0) {
          p.x = p.xo + (dm1 + dm2) / 2;
          return;
        }
        p.x = p.xo + (dm1 * doa2 + dm2 * doa1) / dt;
        return;
      }
      do1 = pv.distance(p, rp1, true, true);
      do2 = pv.distance(p, rp2, true, true);
      dm1 = pv.distance(rp1, rp1, false, true);
      dm2 = pv.distance(rp2, rp2, false, true);
      doa1 = Math.abs(do1);
      doa2 = Math.abs(do2);
      dt = doa1 + doa2;
      if (dt === 0) {
        xUnitVector.setRelative(p, p, (dm1 + dm2) / 2, pv, true);
        return;
      }
      xUnitVector.setRelative(p, p, (dm1 * doa2 + dm2 * doa1) / dt, pv, true);
    },
    // Slope of line normal to this
    normalSlope: Number.NEGATIVE_INFINITY,
    // Sets the point 'p' relative to point 'rp'
    // by the distance 'd'.
    //
    // See APPENDIX on SETRELATIVE at the bottom of this file.
    //
    // p   ... point to set
    // rp  ... reference point
    // d   ... distance on projection vector
    // pv  ... projection vector (undefined = this)
    // org ... if true, uses the original position of rp as reference.
    setRelative: function(p, rp, d, pv, org) {
      if (!pv || pv === this) {
        p.x = (org ? rp.xo : rp.x) + d;
        return;
      }
      var rpx = org ? rp.xo : rp.x;
      var rpy = org ? rp.yo : rp.y;
      var rpdx = rpx + d * pv.x;
      var rpdy = rpy + d * pv.y;
      p.x = rpdx + (p.y - rpdy) / pv.normalSlope;
    },
    // Slope of vector line.
    slope: 0,
    // Touches the point p.
    touch: function(p) {
      p.xTouched = true;
    },
    // Tests if a point p is touched.
    touched: function(p) {
      return p.xTouched;
    },
    // Untouches the point p.
    untouch: function(p) {
      p.xTouched = false;
    }
  };
  var yUnitVector = {
    x: 0,
    y: 1,
    axis: "y",
    // Gets the projected distance between two points.
    // o1/o2 ... if true, respective original position is used.
    distance: function(p1, p2, o1, o2) {
      return (o1 ? p1.yo : p1.y) - (o2 ? p2.yo : p2.y);
    },
    // Moves point p so the moved position has the same relative
    // position to the moved positions of rp1 and rp2 than the
    // original positions had.
    //
    // See APPENDIX on INTERPOLATE at the bottom of this file.
    interpolate: function(p, rp1, rp2, pv) {
      var do1;
      var do2;
      var doa1;
      var doa2;
      var dm1;
      var dm2;
      var dt;
      if (!pv || pv === this) {
        do1 = p.yo - rp1.yo;
        do2 = p.yo - rp2.yo;
        dm1 = rp1.y - rp1.yo;
        dm2 = rp2.y - rp2.yo;
        doa1 = Math.abs(do1);
        doa2 = Math.abs(do2);
        dt = doa1 + doa2;
        if (dt === 0) {
          p.y = p.yo + (dm1 + dm2) / 2;
          return;
        }
        p.y = p.yo + (dm1 * doa2 + dm2 * doa1) / dt;
        return;
      }
      do1 = pv.distance(p, rp1, true, true);
      do2 = pv.distance(p, rp2, true, true);
      dm1 = pv.distance(rp1, rp1, false, true);
      dm2 = pv.distance(rp2, rp2, false, true);
      doa1 = Math.abs(do1);
      doa2 = Math.abs(do2);
      dt = doa1 + doa2;
      if (dt === 0) {
        yUnitVector.setRelative(p, p, (dm1 + dm2) / 2, pv, true);
        return;
      }
      yUnitVector.setRelative(p, p, (dm1 * doa2 + dm2 * doa1) / dt, pv, true);
    },
    // Slope of line normal to this.
    normalSlope: 0,
    // Sets the point 'p' relative to point 'rp'
    // by the distance 'd'
    //
    // See APPENDIX on SETRELATIVE at the bottom of this file.
    //
    // p   ... point to set
    // rp  ... reference point
    // d   ... distance on projection vector
    // pv  ... projection vector (undefined = this)
    // org ... if true, uses the original position of rp as reference.
    setRelative: function(p, rp, d, pv, org) {
      if (!pv || pv === this) {
        p.y = (org ? rp.yo : rp.y) + d;
        return;
      }
      var rpx = org ? rp.xo : rp.x;
      var rpy = org ? rp.yo : rp.y;
      var rpdx = rpx + d * pv.x;
      var rpdy = rpy + d * pv.y;
      p.y = rpdy + pv.normalSlope * (p.x - rpdx);
    },
    // Slope of vector line.
    slope: Number.POSITIVE_INFINITY,
    // Touches the point p.
    touch: function(p) {
      p.yTouched = true;
    },
    // Tests if a point p is touched.
    touched: function(p) {
      return p.yTouched;
    },
    // Untouches the point p.
    untouch: function(p) {
      p.yTouched = false;
    }
  };
  Object.freeze(xUnitVector);
  Object.freeze(yUnitVector);
  function UnitVector(x, y) {
    this.x = x;
    this.y = y;
    this.axis = void 0;
    this.slope = y / x;
    this.normalSlope = -x / y;
    Object.freeze(this);
  }
  UnitVector.prototype.distance = function(p1, p2, o1, o2) {
    return this.x * xUnitVector.distance(p1, p2, o1, o2) + this.y * yUnitVector.distance(p1, p2, o1, o2);
  };
  UnitVector.prototype.interpolate = function(p, rp1, rp2, pv) {
    var dm1;
    var dm2;
    var do1;
    var do2;
    var doa1;
    var doa2;
    var dt;
    do1 = pv.distance(p, rp1, true, true);
    do2 = pv.distance(p, rp2, true, true);
    dm1 = pv.distance(rp1, rp1, false, true);
    dm2 = pv.distance(rp2, rp2, false, true);
    doa1 = Math.abs(do1);
    doa2 = Math.abs(do2);
    dt = doa1 + doa2;
    if (dt === 0) {
      this.setRelative(p, p, (dm1 + dm2) / 2, pv, true);
      return;
    }
    this.setRelative(p, p, (dm1 * doa2 + dm2 * doa1) / dt, pv, true);
  };
  UnitVector.prototype.setRelative = function(p, rp, d, pv, org) {
    pv = pv || this;
    var rpx = org ? rp.xo : rp.x;
    var rpy = org ? rp.yo : rp.y;
    var rpdx = rpx + d * pv.x;
    var rpdy = rpy + d * pv.y;
    var pvns = pv.normalSlope;
    var fvs = this.slope;
    var px = p.x;
    var py = p.y;
    p.x = (fvs * px - pvns * rpdx + rpdy - py) / (fvs - pvns);
    p.y = fvs * (p.x - px) + py;
  };
  UnitVector.prototype.touch = function(p) {
    p.xTouched = true;
    p.yTouched = true;
  };
  function getUnitVector(x, y) {
    var d = Math.sqrt(x * x + y * y);
    x /= d;
    y /= d;
    if (x === 1 && y === 0) {
      return xUnitVector;
    } else if (x === 0 && y === 1) {
      return yUnitVector;
    } else {
      return new UnitVector(x, y);
    }
  }
  function HPoint(x, y, lastPointOfContour, onCurve) {
    this.x = this.xo = Math.round(x * 64) / 64;
    this.y = this.yo = Math.round(y * 64) / 64;
    this.lastPointOfContour = lastPointOfContour;
    this.onCurve = onCurve;
    this.prevPointOnContour = void 0;
    this.nextPointOnContour = void 0;
    this.xTouched = false;
    this.yTouched = false;
    Object.preventExtensions(this);
  }
  HPoint.prototype.nextTouched = function(v) {
    var p = this.nextPointOnContour;
    while (!v.touched(p) && p !== this) {
      p = p.nextPointOnContour;
    }
    return p;
  };
  HPoint.prototype.prevTouched = function(v) {
    var p = this.prevPointOnContour;
    while (!v.touched(p) && p !== this) {
      p = p.prevPointOnContour;
    }
    return p;
  };
  var HPZero = Object.freeze(new HPoint(0, 0));
  var defaultState = {
    cvCutIn: 17 / 16,
    // control value cut in
    deltaBase: 9,
    deltaShift: 0.125,
    loop: 1,
    // loops some instructions
    minDis: 1,
    // minimum distance
    autoFlip: true
  };
  function State(env, prog) {
    this.env = env;
    this.stack = [];
    this.prog = prog;
    switch (env) {
      case "glyf":
        this.zp0 = this.zp1 = this.zp2 = 1;
        this.rp0 = this.rp1 = this.rp2 = 0;
      case "prep":
        this.fv = this.pv = this.dpv = xUnitVector;
        this.round = roundToGrid;
    }
  }
  Hinting.prototype.exec = function(glyph, ppem) {
    if (typeof ppem !== "number") {
      throw new Error("Point size is not a number!");
    }
    if (this._errorState > 2) {
      return;
    }
    var font = this.font;
    var prepState = this._prepState;
    if (!prepState || prepState.ppem !== ppem) {
      var fpgmState = this._fpgmState;
      if (!fpgmState) {
        State.prototype = defaultState;
        fpgmState = this._fpgmState = new State("fpgm", font.tables.fpgm);
        fpgmState.funcs = [];
        fpgmState.font = font;
        if (exports.DEBUG) {
          console.log("---EXEC FPGM---");
          fpgmState.step = -1;
        }
        try {
          exec(fpgmState);
        } catch (e) {
          console.log("Hinting error in FPGM:" + e);
          this._errorState = 3;
          return;
        }
      }
      State.prototype = fpgmState;
      prepState = this._prepState = new State("prep", font.tables.prep);
      prepState.ppem = ppem;
      var oCvt = font.tables.cvt;
      if (oCvt) {
        var cvt = prepState.cvt = new Array(oCvt.length);
        var scale = ppem / font.unitsPerEm;
        for (var c = 0; c < oCvt.length; c++) {
          cvt[c] = oCvt[c] * scale;
        }
      } else {
        prepState.cvt = [];
      }
      if (exports.DEBUG) {
        console.log("---EXEC PREP---");
        prepState.step = -1;
      }
      try {
        exec(prepState);
      } catch (e) {
        if (this._errorState < 2) {
          console.log("Hinting error in PREP:" + e);
        }
        this._errorState = 2;
      }
    }
    if (this._errorState > 1) {
      return;
    }
    try {
      return execGlyph(glyph, prepState);
    } catch (e) {
      if (this._errorState < 1) {
        console.log("Hinting error:" + e);
        console.log("Note: further hinting errors are silenced");
      }
      this._errorState = 1;
      return void 0;
    }
  };
  execGlyph = function(glyph, prepState) {
    var xScale = prepState.ppem / prepState.font.unitsPerEm;
    var yScale = xScale;
    var components = glyph.components;
    var contours;
    var gZone;
    var state;
    State.prototype = prepState;
    if (!components) {
      state = new State("glyf", glyph.instructions);
      if (exports.DEBUG) {
        console.log("---EXEC GLYPH---");
        state.step = -1;
      }
      execComponent(glyph, state, xScale, yScale);
      gZone = state.gZone;
    } else {
      var font = prepState.font;
      gZone = [];
      contours = [];
      for (var i = 0; i < components.length; i++) {
        var c = components[i];
        var cg = font.glyphs.get(c.glyphIndex);
        state = new State("glyf", cg.instructions);
        if (exports.DEBUG) {
          console.log("---EXEC COMP " + i + "---");
          state.step = -1;
        }
        execComponent(cg, state, xScale, yScale);
        var dx = Math.round(c.dx * xScale);
        var dy = Math.round(c.dy * yScale);
        var gz = state.gZone;
        var cc = state.contours;
        for (var pi = 0; pi < gz.length; pi++) {
          var p = gz[pi];
          p.xTouched = p.yTouched = false;
          p.xo = p.x = p.x + dx;
          p.yo = p.y = p.y + dy;
        }
        var gLen = gZone.length;
        gZone.push.apply(gZone, gz);
        for (var j = 0; j < cc.length; j++) {
          contours.push(cc[j] + gLen);
        }
      }
      if (glyph.instructions && !state.inhibitGridFit) {
        state = new State("glyf", glyph.instructions);
        state.gZone = state.z0 = state.z1 = state.z2 = gZone;
        state.contours = contours;
        gZone.push(
          new HPoint(0, 0),
          new HPoint(Math.round(glyph.advanceWidth * xScale), 0)
        );
        if (exports.DEBUG) {
          console.log("---EXEC COMPOSITE---");
          state.step = -1;
        }
        exec(state);
        gZone.length -= 2;
      }
    }
    return gZone;
  };
  execComponent = function(glyph, state, xScale, yScale) {
    var points = glyph.points || [];
    var pLen = points.length;
    var gZone = state.gZone = state.z0 = state.z1 = state.z2 = [];
    var contours = state.contours = [];
    var cp;
    for (var i = 0; i < pLen; i++) {
      cp = points[i];
      gZone[i] = new HPoint(
        cp.x * xScale,
        cp.y * yScale,
        cp.lastPointOfContour,
        cp.onCurve
      );
    }
    var sp;
    var np;
    for (var i$1 = 0; i$1 < pLen; i$1++) {
      cp = gZone[i$1];
      if (!sp) {
        sp = cp;
        contours.push(i$1);
      }
      if (cp.lastPointOfContour) {
        cp.nextPointOnContour = sp;
        sp.prevPointOnContour = cp;
        sp = void 0;
      } else {
        np = gZone[i$1 + 1];
        cp.nextPointOnContour = np;
        np.prevPointOnContour = cp;
      }
    }
    if (state.inhibitGridFit) {
      return;
    }
    if (exports.DEBUG) {
      console.log("PROCESSING GLYPH", state.stack);
      for (var i$2 = 0; i$2 < pLen; i$2++) {
        console.log(i$2, gZone[i$2].x, gZone[i$2].y);
      }
    }
    gZone.push(
      new HPoint(0, 0),
      new HPoint(Math.round(glyph.advanceWidth * xScale), 0)
    );
    exec(state);
    gZone.length -= 2;
    if (exports.DEBUG) {
      console.log("FINISHED GLYPH", state.stack);
      for (var i$3 = 0; i$3 < pLen; i$3++) {
        console.log(i$3, gZone[i$3].x, gZone[i$3].y);
      }
    }
  };
  exec = function(state) {
    var prog = state.prog;
    if (!prog) {
      return;
    }
    var pLen = prog.length;
    var ins;
    for (state.ip = 0; state.ip < pLen; state.ip++) {
      if (exports.DEBUG) {
        state.step++;
      }
      ins = instructionTable[prog[state.ip]];
      if (!ins) {
        throw new Error(
          "unknown instruction: 0x" + Number(prog[state.ip]).toString(16)
        );
      }
      ins(state);
    }
  };
  function initTZone(state) {
    var tZone = state.tZone = new Array(state.gZone.length);
    for (var i = 0; i < tZone.length; i++) {
      tZone[i] = new HPoint(0, 0);
    }
  }
  function skip(state, handleElse) {
    var prog = state.prog;
    var ip = state.ip;
    var nesting = 1;
    var ins;
    do {
      ins = prog[++ip];
      if (ins === 88) {
        nesting++;
      } else if (ins === 89) {
        nesting--;
      } else if (ins === 64) {
        ip += prog[ip + 1] + 1;
      } else if (ins === 65) {
        ip += 2 * prog[ip + 1] + 1;
      } else if (ins >= 176 && ins <= 183) {
        ip += ins - 176 + 1;
      } else if (ins >= 184 && ins <= 191) {
        ip += (ins - 184 + 1) * 2;
      } else if (handleElse && nesting === 1 && ins === 27) {
        break;
      }
    } while (nesting > 0);
    state.ip = ip;
  }
  function SVTCA(v, state) {
    if (exports.DEBUG) {
      console.log(state.step, "SVTCA[" + v.axis + "]");
    }
    state.fv = state.pv = state.dpv = v;
  }
  function SPVTCA(v, state) {
    if (exports.DEBUG) {
      console.log(state.step, "SPVTCA[" + v.axis + "]");
    }
    state.pv = state.dpv = v;
  }
  function SFVTCA(v, state) {
    if (exports.DEBUG) {
      console.log(state.step, "SFVTCA[" + v.axis + "]");
    }
    state.fv = v;
  }
  function SPVTL(a, state) {
    var stack = state.stack;
    var p2i = stack.pop();
    var p1i = stack.pop();
    var p2 = state.z2[p2i];
    var p1 = state.z1[p1i];
    if (exports.DEBUG) {
      console.log("SPVTL[" + a + "]", p2i, p1i);
    }
    var dx;
    var dy;
    if (!a) {
      dx = p1.x - p2.x;
      dy = p1.y - p2.y;
    } else {
      dx = p2.y - p1.y;
      dy = p1.x - p2.x;
    }
    state.pv = state.dpv = getUnitVector(dx, dy);
  }
  function SFVTL(a, state) {
    var stack = state.stack;
    var p2i = stack.pop();
    var p1i = stack.pop();
    var p2 = state.z2[p2i];
    var p1 = state.z1[p1i];
    if (exports.DEBUG) {
      console.log("SFVTL[" + a + "]", p2i, p1i);
    }
    var dx;
    var dy;
    if (!a) {
      dx = p1.x - p2.x;
      dy = p1.y - p2.y;
    } else {
      dx = p2.y - p1.y;
      dy = p1.x - p2.x;
    }
    state.fv = getUnitVector(dx, dy);
  }
  function SPVFS(state) {
    var stack = state.stack;
    var y = stack.pop();
    var x = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SPVFS[]", y, x);
    }
    state.pv = state.dpv = getUnitVector(x, y);
  }
  function SFVFS(state) {
    var stack = state.stack;
    var y = stack.pop();
    var x = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SPVFS[]", y, x);
    }
    state.fv = getUnitVector(x, y);
  }
  function GPV(state) {
    var stack = state.stack;
    var pv = state.pv;
    if (exports.DEBUG) {
      console.log(state.step, "GPV[]");
    }
    stack.push(pv.x * 16384);
    stack.push(pv.y * 16384);
  }
  function GFV(state) {
    var stack = state.stack;
    var fv = state.fv;
    if (exports.DEBUG) {
      console.log(state.step, "GFV[]");
    }
    stack.push(fv.x * 16384);
    stack.push(fv.y * 16384);
  }
  function SFVTPV(state) {
    state.fv = state.pv;
    if (exports.DEBUG) {
      console.log(state.step, "SFVTPV[]");
    }
  }
  function ISECT(state) {
    var stack = state.stack;
    var pa0i = stack.pop();
    var pa1i = stack.pop();
    var pb0i = stack.pop();
    var pb1i = stack.pop();
    var pi = stack.pop();
    var z0 = state.z0;
    var z1 = state.z1;
    var pa0 = z0[pa0i];
    var pa1 = z0[pa1i];
    var pb0 = z1[pb0i];
    var pb1 = z1[pb1i];
    var p = state.z2[pi];
    if (exports.DEBUG) {
      console.log("ISECT[], ", pa0i, pa1i, pb0i, pb1i, pi);
    }
    var x1 = pa0.x;
    var y1 = pa0.y;
    var x2 = pa1.x;
    var y2 = pa1.y;
    var x3 = pb0.x;
    var y3 = pb0.y;
    var x4 = pb1.x;
    var y4 = pb1.y;
    var div = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
    var f1 = x1 * y2 - y1 * x2;
    var f2 = x3 * y4 - y3 * x4;
    p.x = (f1 * (x3 - x4) - f2 * (x1 - x2)) / div;
    p.y = (f1 * (y3 - y4) - f2 * (y1 - y2)) / div;
  }
  function SRP0(state) {
    state.rp0 = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SRP0[]", state.rp0);
    }
  }
  function SRP1(state) {
    state.rp1 = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SRP1[]", state.rp1);
    }
  }
  function SRP2(state) {
    state.rp2 = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SRP2[]", state.rp2);
    }
  }
  function SZP0(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SZP0[]", n);
    }
    state.zp0 = n;
    switch (n) {
      case 0:
        if (!state.tZone) {
          initTZone(state);
        }
        state.z0 = state.tZone;
        break;
      case 1:
        state.z0 = state.gZone;
        break;
      default:
        throw new Error("Invalid zone pointer");
    }
  }
  function SZP1(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SZP1[]", n);
    }
    state.zp1 = n;
    switch (n) {
      case 0:
        if (!state.tZone) {
          initTZone(state);
        }
        state.z1 = state.tZone;
        break;
      case 1:
        state.z1 = state.gZone;
        break;
      default:
        throw new Error("Invalid zone pointer");
    }
  }
  function SZP2(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SZP2[]", n);
    }
    state.zp2 = n;
    switch (n) {
      case 0:
        if (!state.tZone) {
          initTZone(state);
        }
        state.z2 = state.tZone;
        break;
      case 1:
        state.z2 = state.gZone;
        break;
      default:
        throw new Error("Invalid zone pointer");
    }
  }
  function SZPS(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SZPS[]", n);
    }
    state.zp0 = state.zp1 = state.zp2 = n;
    switch (n) {
      case 0:
        if (!state.tZone) {
          initTZone(state);
        }
        state.z0 = state.z1 = state.z2 = state.tZone;
        break;
      case 1:
        state.z0 = state.z1 = state.z2 = state.gZone;
        break;
      default:
        throw new Error("Invalid zone pointer");
    }
  }
  function SLOOP(state) {
    state.loop = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SLOOP[]", state.loop);
    }
  }
  function RTG(state) {
    if (exports.DEBUG) {
      console.log(state.step, "RTG[]");
    }
    state.round = roundToGrid;
  }
  function RTHG(state) {
    if (exports.DEBUG) {
      console.log(state.step, "RTHG[]");
    }
    state.round = roundToHalfGrid;
  }
  function SMD(state) {
    var d = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SMD[]", d);
    }
    state.minDis = d / 64;
  }
  function ELSE(state) {
    if (exports.DEBUG) {
      console.log(state.step, "ELSE[]");
    }
    skip(state, false);
  }
  function JMPR(state) {
    var o = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "JMPR[]", o);
    }
    state.ip += o - 1;
  }
  function SCVTCI(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SCVTCI[]", n);
    }
    state.cvCutIn = n / 64;
  }
  function DUP(state) {
    var stack = state.stack;
    if (exports.DEBUG) {
      console.log(state.step, "DUP[]");
    }
    stack.push(stack[stack.length - 1]);
  }
  function POP(state) {
    if (exports.DEBUG) {
      console.log(state.step, "POP[]");
    }
    state.stack.pop();
  }
  function CLEAR(state) {
    if (exports.DEBUG) {
      console.log(state.step, "CLEAR[]");
    }
    state.stack.length = 0;
  }
  function SWAP(state) {
    var stack = state.stack;
    var a = stack.pop();
    var b = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SWAP[]");
    }
    stack.push(a);
    stack.push(b);
  }
  function DEPTH(state) {
    var stack = state.stack;
    if (exports.DEBUG) {
      console.log(state.step, "DEPTH[]");
    }
    stack.push(stack.length);
  }
  function LOOPCALL(state) {
    var stack = state.stack;
    var fn = stack.pop();
    var c = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "LOOPCALL[]", fn, c);
    }
    var cip = state.ip;
    var cprog = state.prog;
    state.prog = state.funcs[fn];
    for (var i = 0; i < c; i++) {
      exec(state);
      if (exports.DEBUG) {
        console.log(
          ++state.step,
          i + 1 < c ? "next loopcall" : "done loopcall",
          i
        );
      }
    }
    state.ip = cip;
    state.prog = cprog;
  }
  function CALL(state) {
    var fn = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "CALL[]", fn);
    }
    var cip = state.ip;
    var cprog = state.prog;
    state.prog = state.funcs[fn];
    exec(state);
    state.ip = cip;
    state.prog = cprog;
    if (exports.DEBUG) {
      console.log(++state.step, "returning from", fn);
    }
  }
  function CINDEX(state) {
    var stack = state.stack;
    var k = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "CINDEX[]", k);
    }
    stack.push(stack[stack.length - k]);
  }
  function MINDEX(state) {
    var stack = state.stack;
    var k = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "MINDEX[]", k);
    }
    stack.push(stack.splice(stack.length - k, 1)[0]);
  }
  function FDEF(state) {
    if (state.env !== "fpgm") {
      throw new Error("FDEF not allowed here");
    }
    var stack = state.stack;
    var prog = state.prog;
    var ip = state.ip;
    var fn = stack.pop();
    var ipBegin = ip;
    if (exports.DEBUG) {
      console.log(state.step, "FDEF[]", fn);
    }
    while (prog[++ip] !== 45) {
    }
    state.ip = ip;
    state.funcs[fn] = prog.slice(ipBegin + 1, ip);
  }
  function MDAP(round, state) {
    var pi = state.stack.pop();
    var p = state.z0[pi];
    var fv = state.fv;
    var pv = state.pv;
    if (exports.DEBUG) {
      console.log(state.step, "MDAP[" + round + "]", pi);
    }
    var d = pv.distance(p, HPZero);
    if (round) {
      d = state.round(d);
    }
    fv.setRelative(p, HPZero, d, pv);
    fv.touch(p);
    state.rp0 = state.rp1 = pi;
  }
  function IUP(v, state) {
    var z2 = state.z2;
    var pLen = z2.length - 2;
    var cp;
    var pp;
    var np;
    if (exports.DEBUG) {
      console.log(state.step, "IUP[" + v.axis + "]");
    }
    for (var i = 0; i < pLen; i++) {
      cp = z2[i];
      if (v.touched(cp)) {
        continue;
      }
      pp = cp.prevTouched(v);
      if (pp === cp) {
        continue;
      }
      np = cp.nextTouched(v);
      if (pp === np) {
        v.setRelative(cp, cp, v.distance(pp, pp, false, true), v, true);
      }
      v.interpolate(cp, pp, np, v);
    }
  }
  function SHP(a, state) {
    var stack = state.stack;
    var rpi = a ? state.rp1 : state.rp2;
    var rp = (a ? state.z0 : state.z1)[rpi];
    var fv = state.fv;
    var pv = state.pv;
    var loop = state.loop;
    var z2 = state.z2;
    while (loop--) {
      var pi = stack.pop();
      var p = z2[pi];
      var d = pv.distance(rp, rp, false, true);
      fv.setRelative(p, p, d, pv);
      fv.touch(p);
      if (exports.DEBUG) {
        console.log(
          state.step,
          (state.loop > 1 ? "loop " + (state.loop - loop) + ": " : "") + "SHP[" + (a ? "rp1" : "rp2") + "]",
          pi
        );
      }
    }
    state.loop = 1;
  }
  function SHC(a, state) {
    var stack = state.stack;
    var rpi = a ? state.rp1 : state.rp2;
    var rp = (a ? state.z0 : state.z1)[rpi];
    var fv = state.fv;
    var pv = state.pv;
    var ci = stack.pop();
    var sp = state.z2[state.contours[ci]];
    var p = sp;
    if (exports.DEBUG) {
      console.log(state.step, "SHC[" + a + "]", ci);
    }
    var d = pv.distance(rp, rp, false, true);
    do {
      if (p !== rp) {
        fv.setRelative(p, p, d, pv);
      }
      p = p.nextPointOnContour;
    } while (p !== sp);
  }
  function SHZ(a, state) {
    var stack = state.stack;
    var rpi = a ? state.rp1 : state.rp2;
    var rp = (a ? state.z0 : state.z1)[rpi];
    var fv = state.fv;
    var pv = state.pv;
    var e = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SHZ[" + a + "]", e);
    }
    var z;
    switch (e) {
      case 0:
        z = state.tZone;
        break;
      case 1:
        z = state.gZone;
        break;
      default:
        throw new Error("Invalid zone");
    }
    var p;
    var d = pv.distance(rp, rp, false, true);
    var pLen = z.length - 2;
    for (var i = 0; i < pLen; i++) {
      p = z[i];
      fv.setRelative(p, p, d, pv);
    }
  }
  function SHPIX(state) {
    var stack = state.stack;
    var loop = state.loop;
    var fv = state.fv;
    var d = stack.pop() / 64;
    var z2 = state.z2;
    while (loop--) {
      var pi = stack.pop();
      var p = z2[pi];
      if (exports.DEBUG) {
        console.log(
          state.step,
          (state.loop > 1 ? "loop " + (state.loop - loop) + ": " : "") + "SHPIX[]",
          pi,
          d
        );
      }
      fv.setRelative(p, p, d);
      fv.touch(p);
    }
    state.loop = 1;
  }
  function IP(state) {
    var stack = state.stack;
    var rp1i = state.rp1;
    var rp2i = state.rp2;
    var loop = state.loop;
    var rp1 = state.z0[rp1i];
    var rp2 = state.z1[rp2i];
    var fv = state.fv;
    var pv = state.dpv;
    var z2 = state.z2;
    while (loop--) {
      var pi = stack.pop();
      var p = z2[pi];
      if (exports.DEBUG) {
        console.log(
          state.step,
          (state.loop > 1 ? "loop " + (state.loop - loop) + ": " : "") + "IP[]",
          pi,
          rp1i,
          "<->",
          rp2i
        );
      }
      fv.interpolate(p, rp1, rp2, pv);
      fv.touch(p);
    }
    state.loop = 1;
  }
  function MSIRP(a, state) {
    var stack = state.stack;
    var d = stack.pop() / 64;
    var pi = stack.pop();
    var p = state.z1[pi];
    var rp0 = state.z0[state.rp0];
    var fv = state.fv;
    var pv = state.pv;
    fv.setRelative(p, rp0, d, pv);
    fv.touch(p);
    if (exports.DEBUG) {
      console.log(state.step, "MSIRP[" + a + "]", d, pi);
    }
    state.rp1 = state.rp0;
    state.rp2 = pi;
    if (a) {
      state.rp0 = pi;
    }
  }
  function ALIGNRP(state) {
    var stack = state.stack;
    var rp0i = state.rp0;
    var rp0 = state.z0[rp0i];
    var loop = state.loop;
    var fv = state.fv;
    var pv = state.pv;
    var z1 = state.z1;
    while (loop--) {
      var pi = stack.pop();
      var p = z1[pi];
      if (exports.DEBUG) {
        console.log(
          state.step,
          (state.loop > 1 ? "loop " + (state.loop - loop) + ": " : "") + "ALIGNRP[]",
          pi
        );
      }
      fv.setRelative(p, rp0, 0, pv);
      fv.touch(p);
    }
    state.loop = 1;
  }
  function RTDG(state) {
    if (exports.DEBUG) {
      console.log(state.step, "RTDG[]");
    }
    state.round = roundToDoubleGrid;
  }
  function MIAP(round, state) {
    var stack = state.stack;
    var n = stack.pop();
    var pi = stack.pop();
    var p = state.z0[pi];
    var fv = state.fv;
    var pv = state.pv;
    var cv = state.cvt[n];
    if (exports.DEBUG) {
      console.log(
        state.step,
        "MIAP[" + round + "]",
        n,
        "(",
        cv,
        ")",
        pi
      );
    }
    var d = pv.distance(p, HPZero);
    if (round) {
      if (Math.abs(d - cv) < state.cvCutIn) {
        d = cv;
      }
      d = state.round(d);
    }
    fv.setRelative(p, HPZero, d, pv);
    if (state.zp0 === 0) {
      p.xo = p.x;
      p.yo = p.y;
    }
    fv.touch(p);
    state.rp0 = state.rp1 = pi;
  }
  function NPUSHB(state) {
    var prog = state.prog;
    var ip = state.ip;
    var stack = state.stack;
    var n = prog[++ip];
    if (exports.DEBUG) {
      console.log(state.step, "NPUSHB[]", n);
    }
    for (var i = 0; i < n; i++) {
      stack.push(prog[++ip]);
    }
    state.ip = ip;
  }
  function NPUSHW(state) {
    var ip = state.ip;
    var prog = state.prog;
    var stack = state.stack;
    var n = prog[++ip];
    if (exports.DEBUG) {
      console.log(state.step, "NPUSHW[]", n);
    }
    for (var i = 0; i < n; i++) {
      var w = prog[++ip] << 8 | prog[++ip];
      if (w & 32768) {
        w = -((w ^ 65535) + 1);
      }
      stack.push(w);
    }
    state.ip = ip;
  }
  function WS(state) {
    var stack = state.stack;
    var store = state.store;
    if (!store) {
      store = state.store = [];
    }
    var v = stack.pop();
    var l = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "WS", v, l);
    }
    store[l] = v;
  }
  function RS(state) {
    var stack = state.stack;
    var store = state.store;
    var l = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "RS", l);
    }
    var v = store && store[l] || 0;
    stack.push(v);
  }
  function WCVTP(state) {
    var stack = state.stack;
    var v = stack.pop();
    var l = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "WCVTP", v, l);
    }
    state.cvt[l] = v / 64;
  }
  function RCVT(state) {
    var stack = state.stack;
    var cvte = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "RCVT", cvte);
    }
    stack.push(state.cvt[cvte] * 64);
  }
  function GC(a, state) {
    var stack = state.stack;
    var pi = stack.pop();
    var p = state.z2[pi];
    if (exports.DEBUG) {
      console.log(state.step, "GC[" + a + "]", pi);
    }
    stack.push(state.dpv.distance(p, HPZero, a, false) * 64);
  }
  function MD(a, state) {
    var stack = state.stack;
    var pi2 = stack.pop();
    var pi1 = stack.pop();
    var p2 = state.z1[pi2];
    var p1 = state.z0[pi1];
    var d = state.dpv.distance(p1, p2, a, a);
    if (exports.DEBUG) {
      console.log(state.step, "MD[" + a + "]", pi2, pi1, "->", d);
    }
    state.stack.push(Math.round(d * 64));
  }
  function MPPEM(state) {
    if (exports.DEBUG) {
      console.log(state.step, "MPPEM[]");
    }
    state.stack.push(state.ppem);
  }
  function FLIPON(state) {
    if (exports.DEBUG) {
      console.log(state.step, "FLIPON[]");
    }
    state.autoFlip = true;
  }
  function LT(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "LT[]", e2, e1);
    }
    stack.push(e1 < e2 ? 1 : 0);
  }
  function LTEQ(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "LTEQ[]", e2, e1);
    }
    stack.push(e1 <= e2 ? 1 : 0);
  }
  function GT(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "GT[]", e2, e1);
    }
    stack.push(e1 > e2 ? 1 : 0);
  }
  function GTEQ(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "GTEQ[]", e2, e1);
    }
    stack.push(e1 >= e2 ? 1 : 0);
  }
  function EQ(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "EQ[]", e2, e1);
    }
    stack.push(e2 === e1 ? 1 : 0);
  }
  function NEQ(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "NEQ[]", e2, e1);
    }
    stack.push(e2 !== e1 ? 1 : 0);
  }
  function ODD(state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "ODD[]", n);
    }
    stack.push(Math.trunc(n) % 2 ? 1 : 0);
  }
  function EVEN(state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "EVEN[]", n);
    }
    stack.push(Math.trunc(n) % 2 ? 0 : 1);
  }
  function IF(state) {
    var test = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "IF[]", test);
    }
    if (!test) {
      skip(state, true);
      if (exports.DEBUG) {
        console.log(state.step, "EIF[]");
      }
    }
  }
  function EIF(state) {
    if (exports.DEBUG) {
      console.log(state.step, "EIF[]");
    }
  }
  function AND(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "AND[]", e2, e1);
    }
    stack.push(e2 && e1 ? 1 : 0);
  }
  function OR(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "OR[]", e2, e1);
    }
    stack.push(e2 || e1 ? 1 : 0);
  }
  function NOT(state) {
    var stack = state.stack;
    var e = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "NOT[]", e);
    }
    stack.push(e ? 0 : 1);
  }
  function DELTAP123(b, state) {
    var stack = state.stack;
    var n = stack.pop();
    var fv = state.fv;
    var pv = state.pv;
    var ppem = state.ppem;
    var base = state.deltaBase + (b - 1) * 16;
    var ds = state.deltaShift;
    var z0 = state.z0;
    if (exports.DEBUG) {
      console.log(state.step, "DELTAP[" + b + "]", n, stack);
    }
    for (var i = 0; i < n; i++) {
      var pi = stack.pop();
      var arg = stack.pop();
      var appem = base + ((arg & 240) >> 4);
      if (appem !== ppem) {
        continue;
      }
      var mag = (arg & 15) - 8;
      if (mag >= 0) {
        mag++;
      }
      if (exports.DEBUG) {
        console.log(state.step, "DELTAPFIX", pi, "by", mag * ds);
      }
      var p = z0[pi];
      fv.setRelative(p, p, mag * ds, pv);
    }
  }
  function SDB(state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SDB[]", n);
    }
    state.deltaBase = n;
  }
  function SDS(state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SDS[]", n);
    }
    state.deltaShift = Math.pow(0.5, n);
  }
  function ADD(state) {
    var stack = state.stack;
    var n2 = stack.pop();
    var n1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "ADD[]", n2, n1);
    }
    stack.push(n1 + n2);
  }
  function SUB(state) {
    var stack = state.stack;
    var n2 = stack.pop();
    var n1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SUB[]", n2, n1);
    }
    stack.push(n1 - n2);
  }
  function DIV(state) {
    var stack = state.stack;
    var n2 = stack.pop();
    var n1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "DIV[]", n2, n1);
    }
    stack.push(n1 * 64 / n2);
  }
  function MUL(state) {
    var stack = state.stack;
    var n2 = stack.pop();
    var n1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "MUL[]", n2, n1);
    }
    stack.push(n1 * n2 / 64);
  }
  function ABS(state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "ABS[]", n);
    }
    stack.push(Math.abs(n));
  }
  function NEG(state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "NEG[]", n);
    }
    stack.push(-n);
  }
  function FLOOR(state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "FLOOR[]", n);
    }
    stack.push(Math.floor(n / 64) * 64);
  }
  function CEILING(state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "CEILING[]", n);
    }
    stack.push(Math.ceil(n / 64) * 64);
  }
  function ROUND(dt, state) {
    var stack = state.stack;
    var n = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "ROUND[]");
    }
    stack.push(state.round(n / 64) * 64);
  }
  function WCVTF(state) {
    var stack = state.stack;
    var v = stack.pop();
    var l = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "WCVTF[]", v, l);
    }
    state.cvt[l] = v * state.ppem / state.font.unitsPerEm;
  }
  function DELTAC123(b, state) {
    var stack = state.stack;
    var n = stack.pop();
    var ppem = state.ppem;
    var base = state.deltaBase + (b - 1) * 16;
    var ds = state.deltaShift;
    if (exports.DEBUG) {
      console.log(state.step, "DELTAC[" + b + "]", n, stack);
    }
    for (var i = 0; i < n; i++) {
      var c = stack.pop();
      var arg = stack.pop();
      var appem = base + ((arg & 240) >> 4);
      if (appem !== ppem) {
        continue;
      }
      var mag = (arg & 15) - 8;
      if (mag >= 0) {
        mag++;
      }
      var delta = mag * ds;
      if (exports.DEBUG) {
        console.log(state.step, "DELTACFIX", c, "by", delta);
      }
      state.cvt[c] += delta;
    }
  }
  function SROUND(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SROUND[]", n);
    }
    state.round = roundSuper;
    var period;
    switch (n & 192) {
      case 0:
        period = 0.5;
        break;
      case 64:
        period = 1;
        break;
      case 128:
        period = 2;
        break;
      default:
        throw new Error("invalid SROUND value");
    }
    state.srPeriod = period;
    switch (n & 48) {
      case 0:
        state.srPhase = 0;
        break;
      case 16:
        state.srPhase = 0.25 * period;
        break;
      case 32:
        state.srPhase = 0.5 * period;
        break;
      case 48:
        state.srPhase = 0.75 * period;
        break;
      default:
        throw new Error("invalid SROUND value");
    }
    n &= 15;
    if (n === 0) {
      state.srThreshold = 0;
    } else {
      state.srThreshold = (n / 8 - 0.5) * period;
    }
  }
  function S45ROUND(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "S45ROUND[]", n);
    }
    state.round = roundSuper;
    var period;
    switch (n & 192) {
      case 0:
        period = Math.sqrt(2) / 2;
        break;
      case 64:
        period = Math.sqrt(2);
        break;
      case 128:
        period = 2 * Math.sqrt(2);
        break;
      default:
        throw new Error("invalid S45ROUND value");
    }
    state.srPeriod = period;
    switch (n & 48) {
      case 0:
        state.srPhase = 0;
        break;
      case 16:
        state.srPhase = 0.25 * period;
        break;
      case 32:
        state.srPhase = 0.5 * period;
        break;
      case 48:
        state.srPhase = 0.75 * period;
        break;
      default:
        throw new Error("invalid S45ROUND value");
    }
    n &= 15;
    if (n === 0) {
      state.srThreshold = 0;
    } else {
      state.srThreshold = (n / 8 - 0.5) * period;
    }
  }
  function ROFF(state) {
    if (exports.DEBUG) {
      console.log(state.step, "ROFF[]");
    }
    state.round = roundOff;
  }
  function RUTG(state) {
    if (exports.DEBUG) {
      console.log(state.step, "RUTG[]");
    }
    state.round = roundUpToGrid;
  }
  function RDTG(state) {
    if (exports.DEBUG) {
      console.log(state.step, "RDTG[]");
    }
    state.round = roundDownToGrid;
  }
  function SCANCTRL(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SCANCTRL[]", n);
    }
  }
  function SDPVTL(a, state) {
    var stack = state.stack;
    var p2i = stack.pop();
    var p1i = stack.pop();
    var p2 = state.z2[p2i];
    var p1 = state.z1[p1i];
    if (exports.DEBUG) {
      console.log(state.step, "SDPVTL[" + a + "]", p2i, p1i);
    }
    var dx;
    var dy;
    if (!a) {
      dx = p1.x - p2.x;
      dy = p1.y - p2.y;
    } else {
      dx = p2.y - p1.y;
      dy = p1.x - p2.x;
    }
    state.dpv = getUnitVector(dx, dy);
  }
  function GETINFO(state) {
    var stack = state.stack;
    var sel = stack.pop();
    var r = 0;
    if (exports.DEBUG) {
      console.log(state.step, "GETINFO[]", sel);
    }
    if (sel & 1) {
      r = 35;
    }
    if (sel & 32) {
      r |= 4096;
    }
    stack.push(r);
  }
  function ROLL(state) {
    var stack = state.stack;
    var a = stack.pop();
    var b = stack.pop();
    var c = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "ROLL[]");
    }
    stack.push(b);
    stack.push(a);
    stack.push(c);
  }
  function MAX(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "MAX[]", e2, e1);
    }
    stack.push(Math.max(e1, e2));
  }
  function MIN(state) {
    var stack = state.stack;
    var e2 = stack.pop();
    var e1 = stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "MIN[]", e2, e1);
    }
    stack.push(Math.min(e1, e2));
  }
  function SCANTYPE(state) {
    var n = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "SCANTYPE[]", n);
    }
  }
  function INSTCTRL(state) {
    var s = state.stack.pop();
    var v = state.stack.pop();
    if (exports.DEBUG) {
      console.log(state.step, "INSTCTRL[]", s, v);
    }
    switch (s) {
      case 1:
        state.inhibitGridFit = !!v;
        return;
      case 2:
        state.ignoreCvt = !!v;
        return;
      default:
        throw new Error("invalid INSTCTRL[] selector");
    }
  }
  function PUSHB(n, state) {
    var stack = state.stack;
    var prog = state.prog;
    var ip = state.ip;
    if (exports.DEBUG) {
      console.log(state.step, "PUSHB[" + n + "]");
    }
    for (var i = 0; i < n; i++) {
      stack.push(prog[++ip]);
    }
    state.ip = ip;
  }
  function PUSHW(n, state) {
    var ip = state.ip;
    var prog = state.prog;
    var stack = state.stack;
    if (exports.DEBUG) {
      console.log(state.ip, "PUSHW[" + n + "]");
    }
    for (var i = 0; i < n; i++) {
      var w = prog[++ip] << 8 | prog[++ip];
      if (w & 32768) {
        w = -((w ^ 65535) + 1);
      }
      stack.push(w);
    }
    state.ip = ip;
  }
  function MDRP_MIRP(indirect, setRp0, keepD, ro, dt, state) {
    var stack = state.stack;
    var cvte = indirect && stack.pop();
    var pi = stack.pop();
    var rp0i = state.rp0;
    var rp = state.z0[rp0i];
    var p = state.z1[pi];
    var md = state.minDis;
    var fv = state.fv;
    var pv = state.dpv;
    var od;
    var d;
    var sign;
    var cv;
    d = od = pv.distance(p, rp, true, true);
    sign = d >= 0 ? 1 : -1;
    d = Math.abs(d);
    if (indirect) {
      cv = state.cvt[cvte];
      if (ro && Math.abs(d - cv) < state.cvCutIn) {
        d = cv;
      }
    }
    if (keepD && d < md) {
      d = md;
    }
    if (ro) {
      d = state.round(d);
    }
    fv.setRelative(p, rp, sign * d, pv);
    fv.touch(p);
    if (exports.DEBUG) {
      console.log(
        state.step,
        (indirect ? "MIRP[" : "MDRP[") + (setRp0 ? "M" : "m") + (keepD ? ">" : "_") + (ro ? "R" : "_") + (dt === 0 ? "Gr" : dt === 1 ? "Bl" : dt === 2 ? "Wh" : "") + "]",
        indirect ? cvte + "(" + state.cvt[cvte] + "," + cv + ")" : "",
        pi,
        "(d =",
        od,
        "->",
        sign * d,
        ")"
      );
    }
    state.rp1 = state.rp0;
    state.rp2 = pi;
    if (setRp0) {
      state.rp0 = pi;
    }
  }
  instructionTable = [
    /* 0x00 */
    SVTCA.bind(void 0, yUnitVector),
    /* 0x01 */
    SVTCA.bind(void 0, xUnitVector),
    /* 0x02 */
    SPVTCA.bind(void 0, yUnitVector),
    /* 0x03 */
    SPVTCA.bind(void 0, xUnitVector),
    /* 0x04 */
    SFVTCA.bind(void 0, yUnitVector),
    /* 0x05 */
    SFVTCA.bind(void 0, xUnitVector),
    /* 0x06 */
    SPVTL.bind(void 0, 0),
    /* 0x07 */
    SPVTL.bind(void 0, 1),
    /* 0x08 */
    SFVTL.bind(void 0, 0),
    /* 0x09 */
    SFVTL.bind(void 0, 1),
    /* 0x0A */
    SPVFS,
    /* 0x0B */
    SFVFS,
    /* 0x0C */
    GPV,
    /* 0x0D */
    GFV,
    /* 0x0E */
    SFVTPV,
    /* 0x0F */
    ISECT,
    /* 0x10 */
    SRP0,
    /* 0x11 */
    SRP1,
    /* 0x12 */
    SRP2,
    /* 0x13 */
    SZP0,
    /* 0x14 */
    SZP1,
    /* 0x15 */
    SZP2,
    /* 0x16 */
    SZPS,
    /* 0x17 */
    SLOOP,
    /* 0x18 */
    RTG,
    /* 0x19 */
    RTHG,
    /* 0x1A */
    SMD,
    /* 0x1B */
    ELSE,
    /* 0x1C */
    JMPR,
    /* 0x1D */
    SCVTCI,
    /* 0x1E */
    void 0,
    // TODO SSWCI
    /* 0x1F */
    void 0,
    // TODO SSW
    /* 0x20 */
    DUP,
    /* 0x21 */
    POP,
    /* 0x22 */
    CLEAR,
    /* 0x23 */
    SWAP,
    /* 0x24 */
    DEPTH,
    /* 0x25 */
    CINDEX,
    /* 0x26 */
    MINDEX,
    /* 0x27 */
    void 0,
    // TODO ALIGNPTS
    /* 0x28 */
    void 0,
    /* 0x29 */
    void 0,
    // TODO UTP
    /* 0x2A */
    LOOPCALL,
    /* 0x2B */
    CALL,
    /* 0x2C */
    FDEF,
    /* 0x2D */
    void 0,
    // ENDF (eaten by FDEF)
    /* 0x2E */
    MDAP.bind(void 0, 0),
    /* 0x2F */
    MDAP.bind(void 0, 1),
    /* 0x30 */
    IUP.bind(void 0, yUnitVector),
    /* 0x31 */
    IUP.bind(void 0, xUnitVector),
    /* 0x32 */
    SHP.bind(void 0, 0),
    /* 0x33 */
    SHP.bind(void 0, 1),
    /* 0x34 */
    SHC.bind(void 0, 0),
    /* 0x35 */
    SHC.bind(void 0, 1),
    /* 0x36 */
    SHZ.bind(void 0, 0),
    /* 0x37 */
    SHZ.bind(void 0, 1),
    /* 0x38 */
    SHPIX,
    /* 0x39 */
    IP,
    /* 0x3A */
    MSIRP.bind(void 0, 0),
    /* 0x3B */
    MSIRP.bind(void 0, 1),
    /* 0x3C */
    ALIGNRP,
    /* 0x3D */
    RTDG,
    /* 0x3E */
    MIAP.bind(void 0, 0),
    /* 0x3F */
    MIAP.bind(void 0, 1),
    /* 0x40 */
    NPUSHB,
    /* 0x41 */
    NPUSHW,
    /* 0x42 */
    WS,
    /* 0x43 */
    RS,
    /* 0x44 */
    WCVTP,
    /* 0x45 */
    RCVT,
    /* 0x46 */
    GC.bind(void 0, 0),
    /* 0x47 */
    GC.bind(void 0, 1),
    /* 0x48 */
    void 0,
    // TODO SCFS
    /* 0x49 */
    MD.bind(void 0, 0),
    /* 0x4A */
    MD.bind(void 0, 1),
    /* 0x4B */
    MPPEM,
    /* 0x4C */
    void 0,
    // TODO MPS
    /* 0x4D */
    FLIPON,
    /* 0x4E */
    void 0,
    // TODO FLIPOFF
    /* 0x4F */
    void 0,
    // TODO DEBUG
    /* 0x50 */
    LT,
    /* 0x51 */
    LTEQ,
    /* 0x52 */
    GT,
    /* 0x53 */
    GTEQ,
    /* 0x54 */
    EQ,
    /* 0x55 */
    NEQ,
    /* 0x56 */
    ODD,
    /* 0x57 */
    EVEN,
    /* 0x58 */
    IF,
    /* 0x59 */
    EIF,
    /* 0x5A */
    AND,
    /* 0x5B */
    OR,
    /* 0x5C */
    NOT,
    /* 0x5D */
    DELTAP123.bind(void 0, 1),
    /* 0x5E */
    SDB,
    /* 0x5F */
    SDS,
    /* 0x60 */
    ADD,
    /* 0x61 */
    SUB,
    /* 0x62 */
    DIV,
    /* 0x63 */
    MUL,
    /* 0x64 */
    ABS,
    /* 0x65 */
    NEG,
    /* 0x66 */
    FLOOR,
    /* 0x67 */
    CEILING,
    /* 0x68 */
    ROUND.bind(void 0, 0),
    /* 0x69 */
    ROUND.bind(void 0, 1),
    /* 0x6A */
    ROUND.bind(void 0, 2),
    /* 0x6B */
    ROUND.bind(void 0, 3),
    /* 0x6C */
    void 0,
    // TODO NROUND[ab]
    /* 0x6D */
    void 0,
    // TODO NROUND[ab]
    /* 0x6E */
    void 0,
    // TODO NROUND[ab]
    /* 0x6F */
    void 0,
    // TODO NROUND[ab]
    /* 0x70 */
    WCVTF,
    /* 0x71 */
    DELTAP123.bind(void 0, 2),
    /* 0x72 */
    DELTAP123.bind(void 0, 3),
    /* 0x73 */
    DELTAC123.bind(void 0, 1),
    /* 0x74 */
    DELTAC123.bind(void 0, 2),
    /* 0x75 */
    DELTAC123.bind(void 0, 3),
    /* 0x76 */
    SROUND,
    /* 0x77 */
    S45ROUND,
    /* 0x78 */
    void 0,
    // TODO JROT[]
    /* 0x79 */
    void 0,
    // TODO JROF[]
    /* 0x7A */
    ROFF,
    /* 0x7B */
    void 0,
    /* 0x7C */
    RUTG,
    /* 0x7D */
    RDTG,
    /* 0x7E */
    POP,
    // actually SANGW, supposed to do only a pop though
    /* 0x7F */
    POP,
    // actually AA, supposed to do only a pop though
    /* 0x80 */
    void 0,
    // TODO FLIPPT
    /* 0x81 */
    void 0,
    // TODO FLIPRGON
    /* 0x82 */
    void 0,
    // TODO FLIPRGOFF
    /* 0x83 */
    void 0,
    /* 0x84 */
    void 0,
    /* 0x85 */
    SCANCTRL,
    /* 0x86 */
    SDPVTL.bind(void 0, 0),
    /* 0x87 */
    SDPVTL.bind(void 0, 1),
    /* 0x88 */
    GETINFO,
    /* 0x89 */
    void 0,
    // TODO IDEF
    /* 0x8A */
    ROLL,
    /* 0x8B */
    MAX,
    /* 0x8C */
    MIN,
    /* 0x8D */
    SCANTYPE,
    /* 0x8E */
    INSTCTRL,
    /* 0x8F */
    void 0,
    /* 0x90 */
    void 0,
    /* 0x91 */
    void 0,
    /* 0x92 */
    void 0,
    /* 0x93 */
    void 0,
    /* 0x94 */
    void 0,
    /* 0x95 */
    void 0,
    /* 0x96 */
    void 0,
    /* 0x97 */
    void 0,
    /* 0x98 */
    void 0,
    /* 0x99 */
    void 0,
    /* 0x9A */
    void 0,
    /* 0x9B */
    void 0,
    /* 0x9C */
    void 0,
    /* 0x9D */
    void 0,
    /* 0x9E */
    void 0,
    /* 0x9F */
    void 0,
    /* 0xA0 */
    void 0,
    /* 0xA1 */
    void 0,
    /* 0xA2 */
    void 0,
    /* 0xA3 */
    void 0,
    /* 0xA4 */
    void 0,
    /* 0xA5 */
    void 0,
    /* 0xA6 */
    void 0,
    /* 0xA7 */
    void 0,
    /* 0xA8 */
    void 0,
    /* 0xA9 */
    void 0,
    /* 0xAA */
    void 0,
    /* 0xAB */
    void 0,
    /* 0xAC */
    void 0,
    /* 0xAD */
    void 0,
    /* 0xAE */
    void 0,
    /* 0xAF */
    void 0,
    /* 0xB0 */
    PUSHB.bind(void 0, 1),
    /* 0xB1 */
    PUSHB.bind(void 0, 2),
    /* 0xB2 */
    PUSHB.bind(void 0, 3),
    /* 0xB3 */
    PUSHB.bind(void 0, 4),
    /* 0xB4 */
    PUSHB.bind(void 0, 5),
    /* 0xB5 */
    PUSHB.bind(void 0, 6),
    /* 0xB6 */
    PUSHB.bind(void 0, 7),
    /* 0xB7 */
    PUSHB.bind(void 0, 8),
    /* 0xB8 */
    PUSHW.bind(void 0, 1),
    /* 0xB9 */
    PUSHW.bind(void 0, 2),
    /* 0xBA */
    PUSHW.bind(void 0, 3),
    /* 0xBB */
    PUSHW.bind(void 0, 4),
    /* 0xBC */
    PUSHW.bind(void 0, 5),
    /* 0xBD */
    PUSHW.bind(void 0, 6),
    /* 0xBE */
    PUSHW.bind(void 0, 7),
    /* 0xBF */
    PUSHW.bind(void 0, 8),
    /* 0xC0 */
    MDRP_MIRP.bind(void 0, 0, 0, 0, 0, 0),
    /* 0xC1 */
    MDRP_MIRP.bind(void 0, 0, 0, 0, 0, 1),
    /* 0xC2 */
    MDRP_MIRP.bind(void 0, 0, 0, 0, 0, 2),
    /* 0xC3 */
    MDRP_MIRP.bind(void 0, 0, 0, 0, 0, 3),
    /* 0xC4 */
    MDRP_MIRP.bind(void 0, 0, 0, 0, 1, 0),
    /* 0xC5 */
    MDRP_MIRP.bind(void 0, 0, 0, 0, 1, 1),
    /* 0xC6 */
    MDRP_MIRP.bind(void 0, 0, 0, 0, 1, 2),
    /* 0xC7 */
    MDRP_MIRP.bind(void 0, 0, 0, 0, 1, 3),
    /* 0xC8 */
    MDRP_MIRP.bind(void 0, 0, 0, 1, 0, 0),
    /* 0xC9 */
    MDRP_MIRP.bind(void 0, 0, 0, 1, 0, 1),
    /* 0xCA */
    MDRP_MIRP.bind(void 0, 0, 0, 1, 0, 2),
    /* 0xCB */
    MDRP_MIRP.bind(void 0, 0, 0, 1, 0, 3),
    /* 0xCC */
    MDRP_MIRP.bind(void 0, 0, 0, 1, 1, 0),
    /* 0xCD */
    MDRP_MIRP.bind(void 0, 0, 0, 1, 1, 1),
    /* 0xCE */
    MDRP_MIRP.bind(void 0, 0, 0, 1, 1, 2),
    /* 0xCF */
    MDRP_MIRP.bind(void 0, 0, 0, 1, 1, 3),
    /* 0xD0 */
    MDRP_MIRP.bind(void 0, 0, 1, 0, 0, 0),
    /* 0xD1 */
    MDRP_MIRP.bind(void 0, 0, 1, 0, 0, 1),
    /* 0xD2 */
    MDRP_MIRP.bind(void 0, 0, 1, 0, 0, 2),
    /* 0xD3 */
    MDRP_MIRP.bind(void 0, 0, 1, 0, 0, 3),
    /* 0xD4 */
    MDRP_MIRP.bind(void 0, 0, 1, 0, 1, 0),
    /* 0xD5 */
    MDRP_MIRP.bind(void 0, 0, 1, 0, 1, 1),
    /* 0xD6 */
    MDRP_MIRP.bind(void 0, 0, 1, 0, 1, 2),
    /* 0xD7 */
    MDRP_MIRP.bind(void 0, 0, 1, 0, 1, 3),
    /* 0xD8 */
    MDRP_MIRP.bind(void 0, 0, 1, 1, 0, 0),
    /* 0xD9 */
    MDRP_MIRP.bind(void 0, 0, 1, 1, 0, 1),
    /* 0xDA */
    MDRP_MIRP.bind(void 0, 0, 1, 1, 0, 2),
    /* 0xDB */
    MDRP_MIRP.bind(void 0, 0, 1, 1, 0, 3),
    /* 0xDC */
    MDRP_MIRP.bind(void 0, 0, 1, 1, 1, 0),
    /* 0xDD */
    MDRP_MIRP.bind(void 0, 0, 1, 1, 1, 1),
    /* 0xDE */
    MDRP_MIRP.bind(void 0, 0, 1, 1, 1, 2),
    /* 0xDF */
    MDRP_MIRP.bind(void 0, 0, 1, 1, 1, 3),
    /* 0xE0 */
    MDRP_MIRP.bind(void 0, 1, 0, 0, 0, 0),
    /* 0xE1 */
    MDRP_MIRP.bind(void 0, 1, 0, 0, 0, 1),
    /* 0xE2 */
    MDRP_MIRP.bind(void 0, 1, 0, 0, 0, 2),
    /* 0xE3 */
    MDRP_MIRP.bind(void 0, 1, 0, 0, 0, 3),
    /* 0xE4 */
    MDRP_MIRP.bind(void 0, 1, 0, 0, 1, 0),
    /* 0xE5 */
    MDRP_MIRP.bind(void 0, 1, 0, 0, 1, 1),
    /* 0xE6 */
    MDRP_MIRP.bind(void 0, 1, 0, 0, 1, 2),
    /* 0xE7 */
    MDRP_MIRP.bind(void 0, 1, 0, 0, 1, 3),
    /* 0xE8 */
    MDRP_MIRP.bind(void 0, 1, 0, 1, 0, 0),
    /* 0xE9 */
    MDRP_MIRP.bind(void 0, 1, 0, 1, 0, 1),
    /* 0xEA */
    MDRP_MIRP.bind(void 0, 1, 0, 1, 0, 2),
    /* 0xEB */
    MDRP_MIRP.bind(void 0, 1, 0, 1, 0, 3),
    /* 0xEC */
    MDRP_MIRP.bind(void 0, 1, 0, 1, 1, 0),
    /* 0xED */
    MDRP_MIRP.bind(void 0, 1, 0, 1, 1, 1),
    /* 0xEE */
    MDRP_MIRP.bind(void 0, 1, 0, 1, 1, 2),
    /* 0xEF */
    MDRP_MIRP.bind(void 0, 1, 0, 1, 1, 3),
    /* 0xF0 */
    MDRP_MIRP.bind(void 0, 1, 1, 0, 0, 0),
    /* 0xF1 */
    MDRP_MIRP.bind(void 0, 1, 1, 0, 0, 1),
    /* 0xF2 */
    MDRP_MIRP.bind(void 0, 1, 1, 0, 0, 2),
    /* 0xF3 */
    MDRP_MIRP.bind(void 0, 1, 1, 0, 0, 3),
    /* 0xF4 */
    MDRP_MIRP.bind(void 0, 1, 1, 0, 1, 0),
    /* 0xF5 */
    MDRP_MIRP.bind(void 0, 1, 1, 0, 1, 1),
    /* 0xF6 */
    MDRP_MIRP.bind(void 0, 1, 1, 0, 1, 2),
    /* 0xF7 */
    MDRP_MIRP.bind(void 0, 1, 1, 0, 1, 3),
    /* 0xF8 */
    MDRP_MIRP.bind(void 0, 1, 1, 1, 0, 0),
    /* 0xF9 */
    MDRP_MIRP.bind(void 0, 1, 1, 1, 0, 1),
    /* 0xFA */
    MDRP_MIRP.bind(void 0, 1, 1, 1, 0, 2),
    /* 0xFB */
    MDRP_MIRP.bind(void 0, 1, 1, 1, 0, 3),
    /* 0xFC */
    MDRP_MIRP.bind(void 0, 1, 1, 1, 1, 0),
    /* 0xFD */
    MDRP_MIRP.bind(void 0, 1, 1, 1, 1, 1),
    /* 0xFE */
    MDRP_MIRP.bind(void 0, 1, 1, 1, 1, 2),
    /* 0xFF */
    MDRP_MIRP.bind(void 0, 1, 1, 1, 1, 3)
  ];
  function Token(char) {
    this.char = char;
    this.state = {};
    this.activeState = null;
  }
  function ContextRange(startIndex, endOffset, contextName) {
    this.contextName = contextName;
    this.startIndex = startIndex;
    this.endOffset = endOffset;
  }
  function ContextChecker(contextName, checkStart, checkEnd) {
    this.contextName = contextName;
    this.openRange = null;
    this.ranges = [];
    this.checkStart = checkStart;
    this.checkEnd = checkEnd;
  }
  function ContextParams(context, currentIndex) {
    this.context = context;
    this.index = currentIndex;
    this.length = context.length;
    this.current = context[currentIndex];
    this.backtrack = context.slice(0, currentIndex);
    this.lookahead = context.slice(currentIndex + 1);
  }
  function Event(eventId) {
    this.eventId = eventId;
    this.subscribers = [];
  }
  function initializeCoreEvents(events) {
    var this$1 = this;
    var coreEvents = [
      "start",
      "end",
      "next",
      "newToken",
      "contextStart",
      "contextEnd",
      "insertToken",
      "removeToken",
      "removeRange",
      "replaceToken",
      "replaceRange",
      "composeRUD",
      "updateContextsRanges"
    ];
    coreEvents.forEach(function(eventId) {
      Object.defineProperty(this$1.events, eventId, {
        value: new Event(eventId)
      });
    });
    if (!!events) {
      coreEvents.forEach(function(eventId) {
        var event = events[eventId];
        if (typeof event === "function") {
          this$1.events[eventId].subscribe(event);
        }
      });
    }
    var requiresContextUpdate = [
      "insertToken",
      "removeToken",
      "removeRange",
      "replaceToken",
      "replaceRange",
      "composeRUD"
    ];
    requiresContextUpdate.forEach(function(eventId) {
      this$1.events[eventId].subscribe(
        this$1.updateContextsRanges
      );
    });
  }
  function Tokenizer(events) {
    this.tokens = [];
    this.registeredContexts = {};
    this.contextCheckers = [];
    this.events = {};
    this.registeredModifiers = [];
    initializeCoreEvents.call(this, events);
  }
  Token.prototype.setState = function(key, value) {
    this.state[key] = value;
    this.activeState = { key, value: this.state[key] };
    return this.activeState;
  };
  Token.prototype.getState = function(stateId) {
    return this.state[stateId] || null;
  };
  Tokenizer.prototype.inboundIndex = function(index) {
    return index >= 0 && index < this.tokens.length;
  };
  Tokenizer.prototype.composeRUD = function(RUDs) {
    var this$1 = this;
    var silent = true;
    var state = RUDs.map(function(RUD) {
      return this$1[RUD[0]].apply(this$1, RUD.slice(1).concat(silent));
    });
    var hasFAILObject = function(obj) {
      return typeof obj === "object" && obj.hasOwnProperty("FAIL");
    };
    if (state.every(hasFAILObject)) {
      return {
        FAIL: "composeRUD: one or more operations hasn't completed successfully",
        report: state.filter(hasFAILObject)
      };
    }
    this.dispatch("composeRUD", [state.filter(function(op) {
      return !hasFAILObject(op);
    })]);
  };
  Tokenizer.prototype.replaceRange = function(startIndex, offset, tokens, silent) {
    offset = offset !== null ? offset : this.tokens.length;
    var isTokenType = tokens.every(function(token) {
      return token instanceof Token;
    });
    if (!isNaN(startIndex) && this.inboundIndex(startIndex) && isTokenType) {
      var replaced = this.tokens.splice.apply(
        this.tokens,
        [startIndex, offset].concat(tokens)
      );
      if (!silent) {
        this.dispatch("replaceToken", [startIndex, offset, tokens]);
      }
      return [replaced, tokens];
    } else {
      return { FAIL: "replaceRange: invalid tokens or startIndex." };
    }
  };
  Tokenizer.prototype.replaceToken = function(index, token, silent) {
    if (!isNaN(index) && this.inboundIndex(index) && token instanceof Token) {
      var replaced = this.tokens.splice(index, 1, token);
      if (!silent) {
        this.dispatch("replaceToken", [index, token]);
      }
      return [replaced[0], token];
    } else {
      return { FAIL: "replaceToken: invalid token or index." };
    }
  };
  Tokenizer.prototype.removeRange = function(startIndex, offset, silent) {
    offset = !isNaN(offset) ? offset : this.tokens.length;
    var tokens = this.tokens.splice(startIndex, offset);
    if (!silent) {
      this.dispatch("removeRange", [tokens, startIndex, offset]);
    }
    return tokens;
  };
  Tokenizer.prototype.removeToken = function(index, silent) {
    if (!isNaN(index) && this.inboundIndex(index)) {
      var token = this.tokens.splice(index, 1);
      if (!silent) {
        this.dispatch("removeToken", [token, index]);
      }
      return token;
    } else {
      return { FAIL: "removeToken: invalid token index." };
    }
  };
  Tokenizer.prototype.insertToken = function(tokens, index, silent) {
    var tokenType = tokens.every(
      function(token) {
        return token instanceof Token;
      }
    );
    if (tokenType) {
      this.tokens.splice.apply(
        this.tokens,
        [index, 0].concat(tokens)
      );
      if (!silent) {
        this.dispatch("insertToken", [tokens, index]);
      }
      return tokens;
    } else {
      return { FAIL: "insertToken: invalid token(s)." };
    }
  };
  Tokenizer.prototype.registerModifier = function(modifierId, condition, modifier) {
    this.events.newToken.subscribe(function(token, contextParams) {
      var conditionParams = [token, contextParams];
      var canApplyModifier = condition === null || condition.apply(this, conditionParams) === true;
      var modifierParams = [token, contextParams];
      if (canApplyModifier) {
        var newStateValue = modifier.apply(this, modifierParams);
        token.setState(modifierId, newStateValue);
      }
    });
    this.registeredModifiers.push(modifierId);
  };
  Event.prototype.subscribe = function(eventHandler) {
    if (typeof eventHandler === "function") {
      return this.subscribers.push(eventHandler) - 1;
    } else {
      return { FAIL: "invalid '" + this.eventId + "' event handler" };
    }
  };
  Event.prototype.unsubscribe = function(subsId) {
    this.subscribers.splice(subsId, 1);
  };
  ContextParams.prototype.setCurrentIndex = function(index) {
    this.index = index;
    this.current = this.context[index];
    this.backtrack = this.context.slice(0, index);
    this.lookahead = this.context.slice(index + 1);
  };
  ContextParams.prototype.get = function(offset) {
    switch (true) {
      case offset === 0:
        return this.current;
      case (offset < 0 && Math.abs(offset) <= this.backtrack.length):
        return this.backtrack.slice(offset)[0];
      case (offset > 0 && offset <= this.lookahead.length):
        return this.lookahead[offset - 1];
      default:
        return null;
    }
  };
  Tokenizer.prototype.rangeToText = function(range) {
    if (range instanceof ContextRange) {
      return this.getRangeTokens(range).map(function(token) {
        return token.char;
      }).join("");
    }
  };
  Tokenizer.prototype.getText = function() {
    return this.tokens.map(function(token) {
      return token.char;
    }).join("");
  };
  Tokenizer.prototype.getContext = function(contextName) {
    var context = this.registeredContexts[contextName];
    return !!context ? context : null;
  };
  Tokenizer.prototype.on = function(eventName, eventHandler) {
    var event = this.events[eventName];
    if (!!event) {
      return event.subscribe(eventHandler);
    } else {
      return null;
    }
  };
  Tokenizer.prototype.dispatch = function(eventName, args) {
    var this$1 = this;
    var event = this.events[eventName];
    if (event instanceof Event) {
      event.subscribers.forEach(function(subscriber) {
        subscriber.apply(this$1, args || []);
      });
    }
  };
  Tokenizer.prototype.registerContextChecker = function(contextName, contextStartCheck, contextEndCheck) {
    if (!!this.getContext(contextName)) {
      return {
        FAIL: "context name '" + contextName + "' is already registered."
      };
    }
    if (typeof contextStartCheck !== "function") {
      return {
        FAIL: "missing context start check."
      };
    }
    if (typeof contextEndCheck !== "function") {
      return {
        FAIL: "missing context end check."
      };
    }
    var contextCheckers = new ContextChecker(
      contextName,
      contextStartCheck,
      contextEndCheck
    );
    this.registeredContexts[contextName] = contextCheckers;
    this.contextCheckers.push(contextCheckers);
    return contextCheckers;
  };
  Tokenizer.prototype.getRangeTokens = function(range) {
    var endIndex = range.startIndex + range.endOffset;
    return [].concat(
      this.tokens.slice(range.startIndex, endIndex)
    );
  };
  Tokenizer.prototype.getContextRanges = function(contextName) {
    var context = this.getContext(contextName);
    if (!!context) {
      return context.ranges;
    } else {
      return { FAIL: "context checker '" + contextName + "' is not registered." };
    }
  };
  Tokenizer.prototype.resetContextsRanges = function() {
    var registeredContexts = this.registeredContexts;
    for (var contextName in registeredContexts) {
      if (registeredContexts.hasOwnProperty(contextName)) {
        var context = registeredContexts[contextName];
        context.ranges = [];
      }
    }
  };
  Tokenizer.prototype.updateContextsRanges = function() {
    this.resetContextsRanges();
    var chars = this.tokens.map(function(token) {
      return token.char;
    });
    for (var i = 0; i < chars.length; i++) {
      var contextParams = new ContextParams(chars, i);
      this.runContextCheck(contextParams);
    }
    this.dispatch("updateContextsRanges", [this.registeredContexts]);
  };
  Tokenizer.prototype.setEndOffset = function(offset, contextName) {
    var startIndex = this.getContext(contextName).openRange.startIndex;
    var range = new ContextRange(startIndex, offset, contextName);
    var ranges = this.getContext(contextName).ranges;
    range.rangeId = contextName + "." + ranges.length;
    ranges.push(range);
    this.getContext(contextName).openRange = null;
    return range;
  };
  Tokenizer.prototype.runContextCheck = function(contextParams) {
    var this$1 = this;
    var index = contextParams.index;
    this.contextCheckers.forEach(function(contextChecker) {
      var contextName = contextChecker.contextName;
      var openRange = this$1.getContext(contextName).openRange;
      if (!openRange && contextChecker.checkStart(contextParams)) {
        openRange = new ContextRange(index, null, contextName);
        this$1.getContext(contextName).openRange = openRange;
        this$1.dispatch("contextStart", [contextName, index]);
      }
      if (!!openRange && contextChecker.checkEnd(contextParams)) {
        var offset = index - openRange.startIndex + 1;
        var range = this$1.setEndOffset(offset, contextName);
        this$1.dispatch("contextEnd", [contextName, range]);
      }
    });
  };
  Tokenizer.prototype.tokenize = function(text) {
    this.tokens = [];
    this.resetContextsRanges();
    var chars = Array.from(text);
    this.dispatch("start");
    for (var i = 0; i < chars.length; i++) {
      var char = chars[i];
      var contextParams = new ContextParams(chars, i);
      this.dispatch("next", [contextParams]);
      this.runContextCheck(contextParams);
      var token = new Token(char);
      this.tokens.push(token);
      this.dispatch("newToken", [token, contextParams]);
    }
    this.dispatch("end", [this.tokens]);
    return this.tokens;
  };
  function isArabicChar(c) {
    return /[\u0600-\u065F\u066A-\u06D2\u06FA-\u06FF]/.test(c);
  }
  function isIsolatedArabicChar(char) {
    return /[\u0630\u0690\u0621\u0631\u0661\u0671\u0622\u0632\u0672\u0692\u06C2\u0623\u0673\u0693\u06C3\u0624\u0694\u06C4\u0625\u0675\u0695\u06C5\u06E5\u0676\u0696\u06C6\u0627\u0677\u0697\u06C7\u0648\u0688\u0698\u06C8\u0689\u0699\u06C9\u068A\u06CA\u066B\u068B\u06CB\u068C\u068D\u06CD\u06FD\u068E\u06EE\u06FE\u062F\u068F\u06CF\u06EF]/.test(char);
  }
  function isTashkeelArabicChar(char) {
    return /[\u0600-\u0605\u060C-\u060E\u0610-\u061B\u061E\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]/.test(char);
  }
  function isLatinChar(c) {
    return /[A-z]/.test(c);
  }
  function isWhiteSpace(c) {
    return /\s/.test(c);
  }
  function FeatureQuery(font) {
    this.font = font;
    this.features = {};
  }
  function SubstitutionAction(action) {
    this.id = action.id;
    this.tag = action.tag;
    this.substitution = action.substitution;
  }
  function lookupCoverage(glyphIndex, coverage) {
    if (!glyphIndex) {
      return -1;
    }
    switch (coverage.format) {
      case 1:
        return coverage.glyphs.indexOf(glyphIndex);
      case 2:
        var ranges = coverage.ranges;
        for (var i = 0; i < ranges.length; i++) {
          var range = ranges[i];
          if (glyphIndex >= range.start && glyphIndex <= range.end) {
            var offset = glyphIndex - range.start;
            return range.index + offset;
          }
        }
        break;
      default:
        return -1;
    }
    return -1;
  }
  function singleSubstitutionFormat1(glyphIndex, subtable) {
    var substituteIndex = lookupCoverage(glyphIndex, subtable.coverage);
    if (substituteIndex === -1) {
      return null;
    }
    return glyphIndex + subtable.deltaGlyphId;
  }
  function singleSubstitutionFormat2(glyphIndex, subtable) {
    var substituteIndex = lookupCoverage(glyphIndex, subtable.coverage);
    if (substituteIndex === -1) {
      return null;
    }
    return subtable.substitute[substituteIndex];
  }
  function lookupCoverageList(coverageList, contextParams) {
    var lookupList = [];
    for (var i = 0; i < coverageList.length; i++) {
      var coverage = coverageList[i];
      var glyphIndex = contextParams.current;
      glyphIndex = Array.isArray(glyphIndex) ? glyphIndex[0] : glyphIndex;
      var lookupIndex = lookupCoverage(glyphIndex, coverage);
      if (lookupIndex !== -1) {
        lookupList.push(lookupIndex);
      }
    }
    if (lookupList.length !== coverageList.length) {
      return -1;
    }
    return lookupList;
  }
  function chainingSubstitutionFormat3(contextParams, subtable) {
    var lookupsCount = subtable.inputCoverage.length + subtable.lookaheadCoverage.length + subtable.backtrackCoverage.length;
    if (contextParams.context.length < lookupsCount) {
      return [];
    }
    var inputLookups = lookupCoverageList(
      subtable.inputCoverage,
      contextParams
    );
    if (inputLookups === -1) {
      return [];
    }
    var lookaheadOffset = subtable.inputCoverage.length - 1;
    if (contextParams.lookahead.length < subtable.lookaheadCoverage.length) {
      return [];
    }
    var lookaheadContext = contextParams.lookahead.slice(lookaheadOffset);
    while (lookaheadContext.length && isTashkeelArabicChar(lookaheadContext[0].char)) {
      lookaheadContext.shift();
    }
    var lookaheadParams = new ContextParams(lookaheadContext, 0);
    var lookaheadLookups = lookupCoverageList(
      subtable.lookaheadCoverage,
      lookaheadParams
    );
    var backtrackContext = [].concat(contextParams.backtrack);
    backtrackContext.reverse();
    while (backtrackContext.length && isTashkeelArabicChar(backtrackContext[0].char)) {
      backtrackContext.shift();
    }
    if (backtrackContext.length < subtable.backtrackCoverage.length) {
      return [];
    }
    var backtrackParams = new ContextParams(backtrackContext, 0);
    var backtrackLookups = lookupCoverageList(
      subtable.backtrackCoverage,
      backtrackParams
    );
    var contextRulesMatch = inputLookups.length === subtable.inputCoverage.length && lookaheadLookups.length === subtable.lookaheadCoverage.length && backtrackLookups.length === subtable.backtrackCoverage.length;
    var substitutions = [];
    if (contextRulesMatch) {
      for (var i = 0; i < subtable.lookupRecords.length; i++) {
        var lookupRecord = subtable.lookupRecords[i];
        var lookupListIndex = lookupRecord.lookupListIndex;
        var lookupTable = this.getLookupByIndex(lookupListIndex);
        for (var s = 0; s < lookupTable.subtables.length; s++) {
          var subtable$1 = lookupTable.subtables[s];
          var lookup = this.getLookupMethod(lookupTable, subtable$1);
          var substitutionType = this.getSubstitutionType(lookupTable, subtable$1);
          if (substitutionType === "12") {
            for (var n = 0; n < inputLookups.length; n++) {
              var glyphIndex = contextParams.get(n);
              var substitution = lookup(glyphIndex);
              if (substitution) {
                substitutions.push(substitution);
              }
            }
          }
        }
      }
    }
    return substitutions;
  }
  function ligatureSubstitutionFormat1(contextParams, subtable) {
    var glyphIndex = contextParams.current;
    var ligSetIndex = lookupCoverage(glyphIndex, subtable.coverage);
    if (ligSetIndex === -1) {
      return null;
    }
    var ligature;
    var ligatureSet = subtable.ligatureSets[ligSetIndex];
    for (var s = 0; s < ligatureSet.length; s++) {
      ligature = ligatureSet[s];
      for (var l = 0; l < ligature.components.length; l++) {
        var lookaheadItem = contextParams.lookahead[l];
        var component = ligature.components[l];
        if (lookaheadItem !== component) {
          break;
        }
        if (l === ligature.components.length - 1) {
          return ligature;
        }
      }
    }
    return null;
  }
  function decompositionSubstitutionFormat1(glyphIndex, subtable) {
    var substituteIndex = lookupCoverage(glyphIndex, subtable.coverage);
    if (substituteIndex === -1) {
      return null;
    }
    return subtable.sequences[substituteIndex];
  }
  FeatureQuery.prototype.getDefaultScriptFeaturesIndexes = function() {
    var scripts = this.font.tables.gsub.scripts;
    for (var s = 0; s < scripts.length; s++) {
      var script = scripts[s];
      if (script.tag === "DFLT") {
        return script.script.defaultLangSys.featureIndexes;
      }
    }
    return [];
  };
  FeatureQuery.prototype.getScriptFeaturesIndexes = function(scriptTag) {
    var tables = this.font.tables;
    if (!tables.gsub) {
      return [];
    }
    if (!scriptTag) {
      return this.getDefaultScriptFeaturesIndexes();
    }
    var scripts = this.font.tables.gsub.scripts;
    for (var i = 0; i < scripts.length; i++) {
      var script = scripts[i];
      if (script.tag === scriptTag && script.script.defaultLangSys) {
        return script.script.defaultLangSys.featureIndexes;
      } else {
        var langSysRecords = script.langSysRecords;
        if (!!langSysRecords) {
          for (var j = 0; j < langSysRecords.length; j++) {
            var langSysRecord = langSysRecords[j];
            if (langSysRecord.tag === scriptTag) {
              var langSys = langSysRecord.langSys;
              return langSys.featureIndexes;
            }
          }
        }
      }
    }
    return this.getDefaultScriptFeaturesIndexes();
  };
  FeatureQuery.prototype.mapTagsToFeatures = function(features, scriptTag) {
    var tags = {};
    for (var i = 0; i < features.length; i++) {
      var tag = features[i].tag;
      var feature = features[i].feature;
      tags[tag] = feature;
    }
    this.features[scriptTag].tags = tags;
  };
  FeatureQuery.prototype.getScriptFeatures = function(scriptTag) {
    var features = this.features[scriptTag];
    if (this.features.hasOwnProperty(scriptTag)) {
      return features;
    }
    var featuresIndexes = this.getScriptFeaturesIndexes(scriptTag);
    if (!featuresIndexes) {
      return null;
    }
    var gsub2 = this.font.tables.gsub;
    features = featuresIndexes.map(function(index) {
      return gsub2.features[index];
    });
    this.features[scriptTag] = features;
    this.mapTagsToFeatures(features, scriptTag);
    return features;
  };
  FeatureQuery.prototype.getSubstitutionType = function(lookupTable, subtable) {
    var lookupType = lookupTable.lookupType.toString();
    var substFormat = subtable.substFormat.toString();
    return lookupType + substFormat;
  };
  FeatureQuery.prototype.getLookupMethod = function(lookupTable, subtable) {
    var this$1 = this;
    var substitutionType = this.getSubstitutionType(lookupTable, subtable);
    switch (substitutionType) {
      case "11":
        return function(glyphIndex) {
          return singleSubstitutionFormat1.apply(
            this$1,
            [glyphIndex, subtable]
          );
        };
      case "12":
        return function(glyphIndex) {
          return singleSubstitutionFormat2.apply(
            this$1,
            [glyphIndex, subtable]
          );
        };
      case "63":
        return function(contextParams) {
          return chainingSubstitutionFormat3.apply(
            this$1,
            [contextParams, subtable]
          );
        };
      case "41":
        return function(contextParams) {
          return ligatureSubstitutionFormat1.apply(
            this$1,
            [contextParams, subtable]
          );
        };
      case "21":
        return function(glyphIndex) {
          return decompositionSubstitutionFormat1.apply(
            this$1,
            [glyphIndex, subtable]
          );
        };
      default:
        throw new Error(
          "lookupType: " + lookupTable.lookupType + " - substFormat: " + subtable.substFormat + " is not yet supported"
        );
    }
  };
  FeatureQuery.prototype.lookupFeature = function(query) {
    var contextParams = query.contextParams;
    var currentIndex = contextParams.index;
    var feature = this.getFeature({
      tag: query.tag,
      script: query.script
    });
    if (!feature) {
      return new Error(
        "font '" + this.font.names.fullName.en + "' doesn't support feature '" + query.tag + "' for script '" + query.script + "'."
      );
    }
    var lookups = this.getFeatureLookups(feature);
    var substitutions = [].concat(contextParams.context);
    for (var l = 0; l < lookups.length; l++) {
      var lookupTable = lookups[l];
      var subtables = this.getLookupSubtables(lookupTable);
      for (var s = 0; s < subtables.length; s++) {
        var subtable = subtables[s];
        var substType = this.getSubstitutionType(lookupTable, subtable);
        var lookup = this.getLookupMethod(lookupTable, subtable);
        var substitution = void 0;
        switch (substType) {
          case "11":
            substitution = lookup(contextParams.current);
            if (substitution) {
              substitutions.splice(currentIndex, 1, new SubstitutionAction({
                id: 11,
                tag: query.tag,
                substitution
              }));
            }
            break;
          case "12":
            substitution = lookup(contextParams.current);
            if (substitution) {
              substitutions.splice(currentIndex, 1, new SubstitutionAction({
                id: 12,
                tag: query.tag,
                substitution
              }));
            }
            break;
          case "63":
            substitution = lookup(contextParams);
            if (Array.isArray(substitution) && substitution.length) {
              substitutions.splice(currentIndex, 1, new SubstitutionAction({
                id: 63,
                tag: query.tag,
                substitution
              }));
            }
            break;
          case "41":
            substitution = lookup(contextParams);
            if (substitution) {
              substitutions.splice(currentIndex, 1, new SubstitutionAction({
                id: 41,
                tag: query.tag,
                substitution
              }));
            }
            break;
          case "21":
            substitution = lookup(contextParams.current);
            if (substitution) {
              substitutions.splice(currentIndex, 1, new SubstitutionAction({
                id: 21,
                tag: query.tag,
                substitution
              }));
            }
            break;
        }
        contextParams = new ContextParams(substitutions, currentIndex);
        if (Array.isArray(substitution) && !substitution.length) {
          continue;
        }
        substitution = null;
      }
    }
    return substitutions.length ? substitutions : null;
  };
  FeatureQuery.prototype.supports = function(query) {
    if (!query.script) {
      return false;
    }
    this.getScriptFeatures(query.script);
    var supportedScript = this.features.hasOwnProperty(query.script);
    if (!query.tag) {
      return supportedScript;
    }
    var supportedFeature = this.features[query.script].some(function(feature) {
      return feature.tag === query.tag;
    });
    return supportedScript && supportedFeature;
  };
  FeatureQuery.prototype.getLookupSubtables = function(lookupTable) {
    return lookupTable.subtables || null;
  };
  FeatureQuery.prototype.getLookupByIndex = function(index) {
    var lookups = this.font.tables.gsub.lookups;
    return lookups[index] || null;
  };
  FeatureQuery.prototype.getFeatureLookups = function(feature) {
    return feature.lookupListIndexes.map(this.getLookupByIndex.bind(this));
  };
  FeatureQuery.prototype.getFeature = function getFeature(query) {
    if (!this.font) {
      return { FAIL: "No font was found" };
    }
    if (!this.features.hasOwnProperty(query.script)) {
      this.getScriptFeatures(query.script);
    }
    var scriptFeatures = this.features[query.script];
    if (!scriptFeatures) {
      return { FAIL: "No feature for script " + query.script };
    }
    if (!scriptFeatures.tags[query.tag]) {
      return null;
    }
    return this.features[query.script].tags[query.tag];
  };
  function arabicWordStartCheck(contextParams) {
    var char = contextParams.current;
    var prevChar = contextParams.get(-1);
    return (
      // ? arabic first char
      prevChar === null && isArabicChar(char) || // ? arabic char preceded with a non arabic char
      !isArabicChar(prevChar) && isArabicChar(char)
    );
  }
  function arabicWordEndCheck(contextParams) {
    var nextChar = contextParams.get(1);
    return (
      // ? last arabic char
      nextChar === null || // ? next char is not arabic
      !isArabicChar(nextChar)
    );
  }
  var arabicWordCheck = {
    startCheck: arabicWordStartCheck,
    endCheck: arabicWordEndCheck
  };
  function arabicSentenceStartCheck(contextParams) {
    var char = contextParams.current;
    var prevChar = contextParams.get(-1);
    return (
      // ? an arabic char preceded with a non arabic char
      (isArabicChar(char) || isTashkeelArabicChar(char)) && !isArabicChar(prevChar)
    );
  }
  function arabicSentenceEndCheck(contextParams) {
    var nextChar = contextParams.get(1);
    switch (true) {
      case nextChar === null:
        return true;
      case (!isArabicChar(nextChar) && !isTashkeelArabicChar(nextChar)):
        var nextIsWhitespace = isWhiteSpace(nextChar);
        if (!nextIsWhitespace) {
          return true;
        }
        if (nextIsWhitespace) {
          var arabicCharAhead = false;
          arabicCharAhead = contextParams.lookahead.some(
            function(c) {
              return isArabicChar(c) || isTashkeelArabicChar(c);
            }
          );
          if (!arabicCharAhead) {
            return true;
          }
        }
        break;
      default:
        return false;
    }
  }
  var arabicSentenceCheck = {
    startCheck: arabicSentenceStartCheck,
    endCheck: arabicSentenceEndCheck
  };
  function singleSubstitutionFormat1$1(action, tokens, index) {
    tokens[index].setState(action.tag, action.substitution);
  }
  function singleSubstitutionFormat2$1(action, tokens, index) {
    tokens[index].setState(action.tag, action.substitution);
  }
  function chainingSubstitutionFormat3$1(action, tokens, index) {
    action.substitution.forEach(function(subst, offset) {
      var token = tokens[index + offset];
      token.setState(action.tag, subst);
    });
  }
  function ligatureSubstitutionFormat1$1(action, tokens, index) {
    var token = tokens[index];
    token.setState(action.tag, action.substitution.ligGlyph);
    var compsCount = action.substitution.components.length;
    for (var i = 0; i < compsCount; i++) {
      token = tokens[index + i + 1];
      token.setState("deleted", true);
    }
  }
  var SUBSTITUTIONS = {
    11: singleSubstitutionFormat1$1,
    12: singleSubstitutionFormat2$1,
    63: chainingSubstitutionFormat3$1,
    41: ligatureSubstitutionFormat1$1
  };
  function applySubstitution(action, tokens, index) {
    if (action instanceof SubstitutionAction && SUBSTITUTIONS[action.id]) {
      SUBSTITUTIONS[action.id](action, tokens, index);
    }
  }
  function willConnectPrev(charContextParams) {
    var backtrack = [].concat(charContextParams.backtrack);
    for (var i = backtrack.length - 1; i >= 0; i--) {
      var prevChar = backtrack[i];
      var isolated = isIsolatedArabicChar(prevChar);
      var tashkeel = isTashkeelArabicChar(prevChar);
      if (!isolated && !tashkeel) {
        return true;
      }
      if (isolated) {
        return false;
      }
    }
    return false;
  }
  function willConnectNext(charContextParams) {
    if (isIsolatedArabicChar(charContextParams.current)) {
      return false;
    }
    for (var i = 0; i < charContextParams.lookahead.length; i++) {
      var nextChar = charContextParams.lookahead[i];
      var tashkeel = isTashkeelArabicChar(nextChar);
      if (!tashkeel) {
        return true;
      }
    }
    return false;
  }
  function arabicPresentationForms(range) {
    var this$1 = this;
    var script = "arab";
    var tags = this.featuresTags[script];
    var tokens = this.tokenizer.getRangeTokens(range);
    if (tokens.length === 1) {
      return;
    }
    var contextParams = new ContextParams(
      tokens.map(
        function(token) {
          return token.getState("glyphIndex");
        }
      ),
      0
    );
    var charContextParams = new ContextParams(
      tokens.map(
        function(token) {
          return token.char;
        }
      ),
      0
    );
    tokens.forEach(function(token, index) {
      if (isTashkeelArabicChar(token.char)) {
        return;
      }
      contextParams.setCurrentIndex(index);
      charContextParams.setCurrentIndex(index);
      var CONNECT = 0;
      if (willConnectPrev(charContextParams)) {
        CONNECT |= 1;
      }
      if (willConnectNext(charContextParams)) {
        CONNECT |= 2;
      }
      var tag;
      switch (CONNECT) {
        case 1:
          tag = "fina";
          break;
        case 2:
          tag = "init";
          break;
        case 3:
          tag = "medi";
          break;
      }
      if (tags.indexOf(tag) === -1) {
        return;
      }
      var substitutions = this$1.query.lookupFeature({
        tag,
        script,
        contextParams
      });
      if (substitutions instanceof Error) {
        return console.info(substitutions.message);
      }
      substitutions.forEach(function(action, index2) {
        if (action instanceof SubstitutionAction) {
          applySubstitution(action, tokens, index2);
          contextParams.context[index2] = action.substitution;
        }
      });
    });
  }
  function getContextParams(tokens, index) {
    var context = tokens.map(function(token) {
      return token.activeState.value;
    });
    return new ContextParams(context, index || 0);
  }
  function arabicRequiredLigatures(range) {
    var this$1 = this;
    var script = "arab";
    var tokens = this.tokenizer.getRangeTokens(range);
    var contextParams = getContextParams(tokens);
    contextParams.context.forEach(function(glyphIndex, index) {
      contextParams.setCurrentIndex(index);
      var substitutions = this$1.query.lookupFeature({
        tag: "rlig",
        script,
        contextParams
      });
      if (substitutions.length) {
        substitutions.forEach(
          function(action) {
            return applySubstitution(action, tokens, index);
          }
        );
        contextParams = getContextParams(tokens);
      }
    });
  }
  function latinWordStartCheck(contextParams) {
    var char = contextParams.current;
    var prevChar = contextParams.get(-1);
    return (
      // ? latin first char
      prevChar === null && isLatinChar(char) || // ? latin char preceded with a non latin char
      !isLatinChar(prevChar) && isLatinChar(char)
    );
  }
  function latinWordEndCheck(contextParams) {
    var nextChar = contextParams.get(1);
    return (
      // ? last latin char
      nextChar === null || // ? next char is not latin
      !isLatinChar(nextChar)
    );
  }
  var latinWordCheck = {
    startCheck: latinWordStartCheck,
    endCheck: latinWordEndCheck
  };
  function getContextParams$1(tokens, index) {
    var context = tokens.map(function(token) {
      return token.activeState.value;
    });
    return new ContextParams(context, index || 0);
  }
  function latinLigature(range) {
    var this$1 = this;
    var script = "latn";
    var tokens = this.tokenizer.getRangeTokens(range);
    var contextParams = getContextParams$1(tokens);
    contextParams.context.forEach(function(glyphIndex, index) {
      contextParams.setCurrentIndex(index);
      var substitutions = this$1.query.lookupFeature({
        tag: "liga",
        script,
        contextParams
      });
      if (substitutions.length) {
        substitutions.forEach(
          function(action) {
            return applySubstitution(action, tokens, index);
          }
        );
        contextParams = getContextParams$1(tokens);
      }
    });
  }
  function Bidi(baseDir) {
    this.baseDir = baseDir || "ltr";
    this.tokenizer = new Tokenizer();
    this.featuresTags = {};
  }
  Bidi.prototype.setText = function(text) {
    this.text = text;
  };
  Bidi.prototype.contextChecks = {
    latinWordCheck,
    arabicWordCheck,
    arabicSentenceCheck
  };
  function registerContextChecker(checkId) {
    var check2 = this.contextChecks[checkId + "Check"];
    return this.tokenizer.registerContextChecker(
      checkId,
      check2.startCheck,
      check2.endCheck
    );
  }
  function tokenizeText() {
    registerContextChecker.call(this, "latinWord");
    registerContextChecker.call(this, "arabicWord");
    registerContextChecker.call(this, "arabicSentence");
    return this.tokenizer.tokenize(this.text);
  }
  function reverseArabicSentences() {
    var this$1 = this;
    var ranges = this.tokenizer.getContextRanges("arabicSentence");
    ranges.forEach(function(range) {
      var rangeTokens = this$1.tokenizer.getRangeTokens(range);
      this$1.tokenizer.replaceRange(
        range.startIndex,
        range.endOffset,
        rangeTokens.reverse()
      );
    });
  }
  Bidi.prototype.registerFeatures = function(script, tags) {
    var this$1 = this;
    var supportedTags = tags.filter(
      function(tag) {
        return this$1.query.supports({ script, tag });
      }
    );
    if (!this.featuresTags.hasOwnProperty(script)) {
      this.featuresTags[script] = supportedTags;
    } else {
      this.featuresTags[script] = this.featuresTags[script].concat(supportedTags);
    }
  };
  Bidi.prototype.applyFeatures = function(font, features) {
    if (!font) {
      throw new Error(
        "No valid font was provided to apply features"
      );
    }
    if (!this.query) {
      this.query = new FeatureQuery(font);
    }
    for (var f = 0; f < features.length; f++) {
      var feature = features[f];
      if (!this.query.supports({ script: feature.script })) {
        continue;
      }
      this.registerFeatures(feature.script, feature.tags);
    }
  };
  Bidi.prototype.registerModifier = function(modifierId, condition, modifier) {
    this.tokenizer.registerModifier(modifierId, condition, modifier);
  };
  function checkGlyphIndexStatus() {
    if (this.tokenizer.registeredModifiers.indexOf("glyphIndex") === -1) {
      throw new Error(
        "glyphIndex modifier is required to apply arabic presentation features."
      );
    }
  }
  function applyArabicPresentationForms() {
    var this$1 = this;
    var script = "arab";
    if (!this.featuresTags.hasOwnProperty(script)) {
      return;
    }
    checkGlyphIndexStatus.call(this);
    var ranges = this.tokenizer.getContextRanges("arabicWord");
    ranges.forEach(function(range) {
      arabicPresentationForms.call(this$1, range);
    });
  }
  function applyArabicRequireLigatures() {
    var this$1 = this;
    var script = "arab";
    if (!this.featuresTags.hasOwnProperty(script)) {
      return;
    }
    var tags = this.featuresTags[script];
    if (tags.indexOf("rlig") === -1) {
      return;
    }
    checkGlyphIndexStatus.call(this);
    var ranges = this.tokenizer.getContextRanges("arabicWord");
    ranges.forEach(function(range) {
      arabicRequiredLigatures.call(this$1, range);
    });
  }
  function applyLatinLigatures() {
    var this$1 = this;
    var script = "latn";
    if (!this.featuresTags.hasOwnProperty(script)) {
      return;
    }
    var tags = this.featuresTags[script];
    if (tags.indexOf("liga") === -1) {
      return;
    }
    checkGlyphIndexStatus.call(this);
    var ranges = this.tokenizer.getContextRanges("latinWord");
    ranges.forEach(function(range) {
      latinLigature.call(this$1, range);
    });
  }
  Bidi.prototype.checkContextReady = function(contextId) {
    return !!this.tokenizer.getContext(contextId);
  };
  Bidi.prototype.applyFeaturesToContexts = function() {
    if (this.checkContextReady("arabicWord")) {
      applyArabicPresentationForms.call(this);
      applyArabicRequireLigatures.call(this);
    }
    if (this.checkContextReady("latinWord")) {
      applyLatinLigatures.call(this);
    }
    if (this.checkContextReady("arabicSentence")) {
      reverseArabicSentences.call(this);
    }
  };
  Bidi.prototype.processText = function(text) {
    if (!this.text || this.text !== text) {
      this.setText(text);
      tokenizeText.call(this);
      this.applyFeaturesToContexts();
    }
  };
  Bidi.prototype.getBidiText = function(text) {
    this.processText(text);
    return this.tokenizer.getText();
  };
  Bidi.prototype.getTextGlyphs = function(text) {
    this.processText(text);
    var indexes = [];
    for (var i = 0; i < this.tokenizer.tokens.length; i++) {
      var token = this.tokenizer.tokens[i];
      if (token.state.deleted) {
        continue;
      }
      var index = token.activeState.value;
      indexes.push(Array.isArray(index) ? index[0] : index);
    }
    return indexes;
  };
  function Font(options) {
    options = options || {};
    options.tables = options.tables || {};
    if (!options.empty) {
      checkArgument(options.familyName, "When creating a new Font object, familyName is required.");
      checkArgument(options.styleName, "When creating a new Font object, styleName is required.");
      checkArgument(options.unitsPerEm, "When creating a new Font object, unitsPerEm is required.");
      checkArgument(options.ascender, "When creating a new Font object, ascender is required.");
      checkArgument(options.descender <= 0, "When creating a new Font object, negative descender value is required.");
      this.names = {
        fontFamily: { en: options.familyName || " " },
        fontSubfamily: { en: options.styleName || " " },
        fullName: { en: options.fullName || options.familyName + " " + options.styleName },
        // postScriptName may not contain any whitespace
        postScriptName: { en: options.postScriptName || (options.familyName + options.styleName).replace(/\s/g, "") },
        designer: { en: options.designer || " " },
        designerURL: { en: options.designerURL || " " },
        manufacturer: { en: options.manufacturer || " " },
        manufacturerURL: { en: options.manufacturerURL || " " },
        license: { en: options.license || " " },
        licenseURL: { en: options.licenseURL || " " },
        version: { en: options.version || "Version 0.1" },
        description: { en: options.description || " " },
        copyright: { en: options.copyright || " " },
        trademark: { en: options.trademark || " " }
      };
      this.unitsPerEm = options.unitsPerEm || 1e3;
      this.ascender = options.ascender;
      this.descender = options.descender;
      this.createdTimestamp = options.createdTimestamp;
      this.tables = Object.assign(options.tables, {
        os2: Object.assign({
          usWeightClass: options.weightClass || this.usWeightClasses.MEDIUM,
          usWidthClass: options.widthClass || this.usWidthClasses.MEDIUM,
          fsSelection: options.fsSelection || this.fsSelectionValues.REGULAR
        }, options.tables.os2)
      });
    }
    this.supported = true;
    this.glyphs = new glyphset.GlyphSet(this, options.glyphs || []);
    this.encoding = new DefaultEncoding(this);
    this.position = new Position(this);
    this.substitution = new Substitution(this);
    this.tables = this.tables || {};
    this._push = null;
    this._hmtxTableData = {};
    Object.defineProperty(this, "hinting", {
      get: function() {
        if (this._hinting) {
          return this._hinting;
        }
        if (this.outlinesFormat === "truetype") {
          return this._hinting = new Hinting(this);
        }
      }
    });
  }
  Font.prototype.hasChar = function(c) {
    return this.encoding.charToGlyphIndex(c) !== null;
  };
  Font.prototype.charToGlyphIndex = function(s) {
    return this.encoding.charToGlyphIndex(s);
  };
  Font.prototype.charToGlyph = function(c) {
    var glyphIndex = this.charToGlyphIndex(c);
    var glyph = this.glyphs.get(glyphIndex);
    if (!glyph) {
      glyph = this.glyphs.get(0);
    }
    return glyph;
  };
  Font.prototype.updateFeatures = function(options) {
    return this.defaultRenderOptions.features.map(function(feature) {
      if (feature.script === "latn") {
        return {
          script: "latn",
          tags: feature.tags.filter(function(tag) {
            return options[tag];
          })
        };
      } else {
        return feature;
      }
    });
  };
  Font.prototype.stringToGlyphs = function(s, options) {
    var this$1 = this;
    var bidi = new Bidi();
    var charToGlyphIndexMod = function(token) {
      return this$1.charToGlyphIndex(token.char);
    };
    bidi.registerModifier("glyphIndex", null, charToGlyphIndexMod);
    var features = options ? this.updateFeatures(options.features) : this.defaultRenderOptions.features;
    bidi.applyFeatures(this, features);
    var indexes = bidi.getTextGlyphs(s);
    var length = indexes.length;
    var glyphs = new Array(length);
    var notdef = this.glyphs.get(0);
    for (var i = 0; i < length; i += 1) {
      glyphs[i] = this.glyphs.get(indexes[i]) || notdef;
    }
    return glyphs;
  };
  Font.prototype.nameToGlyphIndex = function(name) {
    return this.glyphNames.nameToGlyphIndex(name);
  };
  Font.prototype.nameToGlyph = function(name) {
    var glyphIndex = this.nameToGlyphIndex(name);
    var glyph = this.glyphs.get(glyphIndex);
    if (!glyph) {
      glyph = this.glyphs.get(0);
    }
    return glyph;
  };
  Font.prototype.glyphIndexToName = function(gid) {
    if (!this.glyphNames.glyphIndexToName) {
      return "";
    }
    return this.glyphNames.glyphIndexToName(gid);
  };
  Font.prototype.getKerningValue = function(leftGlyph, rightGlyph) {
    leftGlyph = leftGlyph.index || leftGlyph;
    rightGlyph = rightGlyph.index || rightGlyph;
    var gposKerning = this.position.defaultKerningTables;
    if (gposKerning) {
      return this.position.getKerningValue(gposKerning, leftGlyph, rightGlyph);
    }
    return this.kerningPairs[leftGlyph + "," + rightGlyph] || 0;
  };
  Font.prototype.defaultRenderOptions = {
    kerning: true,
    features: [
      /**
       * these 4 features are required to render Arabic text properly
       * and shouldn't be turned off when rendering arabic text.
       */
      { script: "arab", tags: ["init", "medi", "fina", "rlig"] },
      { script: "latn", tags: ["liga", "rlig"] }
    ]
  };
  Font.prototype.forEachGlyph = function(text, x, y, fontSize, options, callback) {
    x = x !== void 0 ? x : 0;
    y = y !== void 0 ? y : 0;
    fontSize = fontSize !== void 0 ? fontSize : 72;
    options = Object.assign({}, this.defaultRenderOptions, options);
    var fontScale = 1 / this.unitsPerEm * fontSize;
    var glyphs = this.stringToGlyphs(text, options);
    var kerningLookups;
    if (options.kerning) {
      var script = options.script || this.position.getDefaultScriptName();
      kerningLookups = this.position.getKerningTables(script, options.language);
    }
    for (var i = 0; i < glyphs.length; i += 1) {
      var glyph = glyphs[i];
      callback.call(this, glyph, x, y, fontSize, options);
      if (glyph.advanceWidth) {
        x += glyph.advanceWidth * fontScale;
      }
      if (options.kerning && i < glyphs.length - 1) {
        var kerningValue = kerningLookups ? this.position.getKerningValue(kerningLookups, glyph.index, glyphs[i + 1].index) : this.getKerningValue(glyph, glyphs[i + 1]);
        x += kerningValue * fontScale;
      }
      if (options.letterSpacing) {
        x += options.letterSpacing * fontSize;
      } else if (options.tracking) {
        x += options.tracking / 1e3 * fontSize;
      }
    }
    return x;
  };
  Font.prototype.getPath = function(text, x, y, fontSize, options) {
    var fullPath = new Path();
    this.forEachGlyph(text, x, y, fontSize, options, function(glyph, gX, gY, gFontSize) {
      var glyphPath = glyph.getPath(gX, gY, gFontSize, options, this);
      fullPath.extend(glyphPath);
    });
    return fullPath;
  };
  Font.prototype.getPaths = function(text, x, y, fontSize, options) {
    var glyphPaths = [];
    this.forEachGlyph(text, x, y, fontSize, options, function(glyph, gX, gY, gFontSize) {
      var glyphPath = glyph.getPath(gX, gY, gFontSize, options, this);
      glyphPaths.push(glyphPath);
    });
    return glyphPaths;
  };
  Font.prototype.getAdvanceWidth = function(text, fontSize, options) {
    return this.forEachGlyph(text, 0, 0, fontSize, options, function() {
    });
  };
  Font.prototype.draw = function(ctx, text, x, y, fontSize, options) {
    this.getPath(text, x, y, fontSize, options).draw(ctx);
  };
  Font.prototype.drawPoints = function(ctx, text, x, y, fontSize, options) {
    this.forEachGlyph(text, x, y, fontSize, options, function(glyph, gX, gY, gFontSize) {
      glyph.drawPoints(ctx, gX, gY, gFontSize);
    });
  };
  Font.prototype.drawMetrics = function(ctx, text, x, y, fontSize, options) {
    this.forEachGlyph(text, x, y, fontSize, options, function(glyph, gX, gY, gFontSize) {
      glyph.drawMetrics(ctx, gX, gY, gFontSize);
    });
  };
  Font.prototype.getEnglishName = function(name) {
    var translations = this.names[name];
    if (translations) {
      return translations.en;
    }
  };
  Font.prototype.validate = function() {
    var _this = this;
    function assert(predicate, message) {
    }
    function assertNamePresent(name) {
      var englishName = _this.getEnglishName(name);
      assert(englishName && englishName.trim().length > 0);
    }
    assertNamePresent("fontFamily");
    assertNamePresent("weightName");
    assertNamePresent("manufacturer");
    assertNamePresent("copyright");
    assertNamePresent("version");
    assert(this.unitsPerEm > 0);
  };
  Font.prototype.toTables = function() {
    return sfnt.fontToTable(this);
  };
  Font.prototype.toBuffer = function() {
    console.warn("Font.toBuffer is deprecated. Use Font.toArrayBuffer instead.");
    return this.toArrayBuffer();
  };
  Font.prototype.toArrayBuffer = function() {
    var sfntTable = this.toTables();
    var bytes = sfntTable.encode();
    var buffer = new ArrayBuffer(bytes.length);
    var intArray = new Uint8Array(buffer);
    for (var i = 0; i < bytes.length; i++) {
      intArray[i] = bytes[i];
    }
    return buffer;
  };
  Font.prototype.download = function(fileName) {
    var familyName = this.getEnglishName("fontFamily");
    var styleName = this.getEnglishName("fontSubfamily");
    fileName = fileName || familyName.replace(/\s/g, "") + "-" + styleName + ".otf";
    var arrayBuffer = this.toArrayBuffer();
    if (isBrowser()) {
      window.URL = window.URL || window.webkitURL;
      if (window.URL) {
        var dataView = new DataView(arrayBuffer);
        var blob = new Blob([dataView], { type: "font/opentype" });
        var link = document.createElement("a");
        link.href = window.URL.createObjectURL(blob);
        link.download = fileName;
        var event = document.createEvent("MouseEvents");
        event.initEvent("click", true, false);
        link.dispatchEvent(event);
      } else {
        console.warn("Font file could not be downloaded. Try using a different browser.");
      }
    } else {
      var fs2 = require_fs();
      var buffer = arrayBufferToNodeBuffer(arrayBuffer);
      fs2.writeFileSync(fileName, buffer);
    }
  };
  Font.prototype.fsSelectionValues = {
    ITALIC: 1,
    //1
    UNDERSCORE: 2,
    //2
    NEGATIVE: 4,
    //4
    OUTLINED: 8,
    //8
    STRIKEOUT: 16,
    //16
    BOLD: 32,
    //32
    REGULAR: 64,
    //64
    USER_TYPO_METRICS: 128,
    //128
    WWS: 256,
    //256
    OBLIQUE: 512
    //512
  };
  Font.prototype.usWidthClasses = {
    ULTRA_CONDENSED: 1,
    EXTRA_CONDENSED: 2,
    CONDENSED: 3,
    SEMI_CONDENSED: 4,
    MEDIUM: 5,
    SEMI_EXPANDED: 6,
    EXPANDED: 7,
    EXTRA_EXPANDED: 8,
    ULTRA_EXPANDED: 9
  };
  Font.prototype.usWeightClasses = {
    THIN: 100,
    EXTRA_LIGHT: 200,
    LIGHT: 300,
    NORMAL: 400,
    MEDIUM: 500,
    SEMI_BOLD: 600,
    BOLD: 700,
    EXTRA_BOLD: 800,
    BLACK: 900
  };
  function addName(name, names) {
    var nameString = JSON.stringify(name);
    var nameID = 256;
    for (var nameKey in names) {
      var n = parseInt(nameKey);
      if (!n || n < 256) {
        continue;
      }
      if (JSON.stringify(names[nameKey]) === nameString) {
        return n;
      }
      if (nameID <= n) {
        nameID = n + 1;
      }
    }
    names[nameID] = name;
    return nameID;
  }
  function makeFvarAxis(n, axis, names) {
    var nameID = addName(axis.name, names);
    return [
      { name: "tag_" + n, type: "TAG", value: axis.tag },
      { name: "minValue_" + n, type: "FIXED", value: axis.minValue << 16 },
      { name: "defaultValue_" + n, type: "FIXED", value: axis.defaultValue << 16 },
      { name: "maxValue_" + n, type: "FIXED", value: axis.maxValue << 16 },
      { name: "flags_" + n, type: "USHORT", value: 0 },
      { name: "nameID_" + n, type: "USHORT", value: nameID }
    ];
  }
  function parseFvarAxis(data, start, names) {
    var axis = {};
    var p = new parse.Parser(data, start);
    axis.tag = p.parseTag();
    axis.minValue = p.parseFixed();
    axis.defaultValue = p.parseFixed();
    axis.maxValue = p.parseFixed();
    p.skip("uShort", 1);
    axis.name = names[p.parseUShort()] || {};
    return axis;
  }
  function makeFvarInstance(n, inst, axes, names) {
    var nameID = addName(inst.name, names);
    var fields = [
      { name: "nameID_" + n, type: "USHORT", value: nameID },
      { name: "flags_" + n, type: "USHORT", value: 0 }
    ];
    for (var i = 0; i < axes.length; ++i) {
      var axisTag = axes[i].tag;
      fields.push({
        name: "axis_" + n + " " + axisTag,
        type: "FIXED",
        value: inst.coordinates[axisTag] << 16
      });
    }
    return fields;
  }
  function parseFvarInstance(data, start, axes, names) {
    var inst = {};
    var p = new parse.Parser(data, start);
    inst.name = names[p.parseUShort()] || {};
    p.skip("uShort", 1);
    inst.coordinates = {};
    for (var i = 0; i < axes.length; ++i) {
      inst.coordinates[axes[i].tag] = p.parseFixed();
    }
    return inst;
  }
  function makeFvarTable(fvar2, names) {
    var result = new table.Table("fvar", [
      { name: "version", type: "ULONG", value: 65536 },
      { name: "offsetToData", type: "USHORT", value: 0 },
      { name: "countSizePairs", type: "USHORT", value: 2 },
      { name: "axisCount", type: "USHORT", value: fvar2.axes.length },
      { name: "axisSize", type: "USHORT", value: 20 },
      { name: "instanceCount", type: "USHORT", value: fvar2.instances.length },
      { name: "instanceSize", type: "USHORT", value: 4 + fvar2.axes.length * 4 }
    ]);
    result.offsetToData = result.sizeOf();
    for (var i = 0; i < fvar2.axes.length; i++) {
      result.fields = result.fields.concat(makeFvarAxis(i, fvar2.axes[i], names));
    }
    for (var j = 0; j < fvar2.instances.length; j++) {
      result.fields = result.fields.concat(makeFvarInstance(j, fvar2.instances[j], fvar2.axes, names));
    }
    return result;
  }
  function parseFvarTable(data, start, names) {
    var p = new parse.Parser(data, start);
    var tableVersion = p.parseULong();
    check.argument(tableVersion === 65536, "Unsupported fvar table version.");
    var offsetToData = p.parseOffset16();
    p.skip("uShort", 1);
    var axisCount = p.parseUShort();
    var axisSize = p.parseUShort();
    var instanceCount = p.parseUShort();
    var instanceSize = p.parseUShort();
    var axes = [];
    for (var i = 0; i < axisCount; i++) {
      axes.push(parseFvarAxis(data, start + offsetToData + i * axisSize, names));
    }
    var instances = [];
    var instanceStart = start + offsetToData + axisCount * axisSize;
    for (var j = 0; j < instanceCount; j++) {
      instances.push(parseFvarInstance(data, instanceStart + j * instanceSize, axes, names));
    }
    return { axes, instances };
  }
  var fvar = { make: makeFvarTable, parse: parseFvarTable };
  var attachList = function() {
    return {
      coverage: this.parsePointer(Parser2.coverage),
      attachPoints: this.parseList(Parser2.pointer(Parser2.uShortList))
    };
  };
  var caretValue = function() {
    var format = this.parseUShort();
    check.argument(
      format === 1 || format === 2 || format === 3,
      "Unsupported CaretValue table version."
    );
    if (format === 1) {
      return { coordinate: this.parseShort() };
    } else if (format === 2) {
      return { pointindex: this.parseShort() };
    } else if (format === 3) {
      return { coordinate: this.parseShort() };
    }
  };
  var ligGlyph = function() {
    return this.parseList(Parser2.pointer(caretValue));
  };
  var ligCaretList = function() {
    return {
      coverage: this.parsePointer(Parser2.coverage),
      ligGlyphs: this.parseList(Parser2.pointer(ligGlyph))
    };
  };
  var markGlyphSets = function() {
    this.parseUShort();
    return this.parseList(Parser2.pointer(Parser2.coverage));
  };
  function parseGDEFTable(data, start) {
    start = start || 0;
    var p = new Parser2(data, start);
    var tableVersion = p.parseVersion(1);
    check.argument(
      tableVersion === 1 || tableVersion === 1.2 || tableVersion === 1.3,
      "Unsupported GDEF table version."
    );
    var gdef2 = {
      version: tableVersion,
      classDef: p.parsePointer(Parser2.classDef),
      attachList: p.parsePointer(attachList),
      ligCaretList: p.parsePointer(ligCaretList),
      markAttachClassDef: p.parsePointer(Parser2.classDef)
    };
    if (tableVersion >= 1.2) {
      gdef2.markGlyphSets = p.parsePointer(markGlyphSets);
    }
    return gdef2;
  }
  var gdef = { parse: parseGDEFTable };
  var subtableParsers$1 = new Array(10);
  subtableParsers$1[1] = function parseLookup12() {
    var start = this.offset + this.relativeOffset;
    var posformat = this.parseUShort();
    if (posformat === 1) {
      return {
        posFormat: 1,
        coverage: this.parsePointer(Parser2.coverage),
        value: this.parseValueRecord()
      };
    } else if (posformat === 2) {
      return {
        posFormat: 2,
        coverage: this.parsePointer(Parser2.coverage),
        values: this.parseValueRecordList()
      };
    }
    check.assert(false, "0x" + start.toString(16) + ": GPOS lookup type 1 format must be 1 or 2.");
  };
  subtableParsers$1[2] = function parseLookup22() {
    var start = this.offset + this.relativeOffset;
    var posFormat = this.parseUShort();
    check.assert(posFormat === 1 || posFormat === 2, "0x" + start.toString(16) + ": GPOS lookup type 2 format must be 1 or 2.");
    var coverage = this.parsePointer(Parser2.coverage);
    var valueFormat1 = this.parseUShort();
    var valueFormat2 = this.parseUShort();
    if (posFormat === 1) {
      return {
        posFormat,
        coverage,
        valueFormat1,
        valueFormat2,
        pairSets: this.parseList(Parser2.pointer(Parser2.list(function() {
          return {
            // pairValueRecord
            secondGlyph: this.parseUShort(),
            value1: this.parseValueRecord(valueFormat1),
            value2: this.parseValueRecord(valueFormat2)
          };
        })))
      };
    } else if (posFormat === 2) {
      var classDef1 = this.parsePointer(Parser2.classDef);
      var classDef2 = this.parsePointer(Parser2.classDef);
      var class1Count = this.parseUShort();
      var class2Count = this.parseUShort();
      return {
        // Class Pair Adjustment
        posFormat,
        coverage,
        valueFormat1,
        valueFormat2,
        classDef1,
        classDef2,
        class1Count,
        class2Count,
        classRecords: this.parseList(class1Count, Parser2.list(class2Count, function() {
          return {
            value1: this.parseValueRecord(valueFormat1),
            value2: this.parseValueRecord(valueFormat2)
          };
        }))
      };
    }
  };
  subtableParsers$1[3] = function parseLookup32() {
    return { error: "GPOS Lookup 3 not supported" };
  };
  subtableParsers$1[4] = function parseLookup42() {
    return { error: "GPOS Lookup 4 not supported" };
  };
  subtableParsers$1[5] = function parseLookup52() {
    return { error: "GPOS Lookup 5 not supported" };
  };
  subtableParsers$1[6] = function parseLookup62() {
    return { error: "GPOS Lookup 6 not supported" };
  };
  subtableParsers$1[7] = function parseLookup72() {
    return { error: "GPOS Lookup 7 not supported" };
  };
  subtableParsers$1[8] = function parseLookup82() {
    return { error: "GPOS Lookup 8 not supported" };
  };
  subtableParsers$1[9] = function parseLookup9() {
    return { error: "GPOS Lookup 9 not supported" };
  };
  function parseGposTable(data, start) {
    start = start || 0;
    var p = new Parser2(data, start);
    var tableVersion = p.parseVersion(1);
    check.argument(tableVersion === 1 || tableVersion === 1.1, "Unsupported GPOS table version " + tableVersion);
    if (tableVersion === 1) {
      return {
        version: tableVersion,
        scripts: p.parseScriptList(),
        features: p.parseFeatureList(),
        lookups: p.parseLookupList(subtableParsers$1)
      };
    } else {
      return {
        version: tableVersion,
        scripts: p.parseScriptList(),
        features: p.parseFeatureList(),
        lookups: p.parseLookupList(subtableParsers$1),
        variations: p.parseFeatureVariationsList()
      };
    }
  }
  var subtableMakers$1 = new Array(10);
  function makeGposTable(gpos2) {
    return new table.Table("GPOS", [
      { name: "version", type: "ULONG", value: 65536 },
      { name: "scripts", type: "TABLE", value: new table.ScriptList(gpos2.scripts) },
      { name: "features", type: "TABLE", value: new table.FeatureList(gpos2.features) },
      { name: "lookups", type: "TABLE", value: new table.LookupList(gpos2.lookups, subtableMakers$1) }
    ]);
  }
  var gpos = { parse: parseGposTable, make: makeGposTable };
  function parseWindowsKernTable(p) {
    var pairs = {};
    p.skip("uShort");
    var subtableVersion = p.parseUShort();
    check.argument(subtableVersion === 0, "Unsupported kern sub-table version.");
    p.skip("uShort", 2);
    var nPairs = p.parseUShort();
    p.skip("uShort", 3);
    for (var i = 0; i < nPairs; i += 1) {
      var leftIndex = p.parseUShort();
      var rightIndex = p.parseUShort();
      var value = p.parseShort();
      pairs[leftIndex + "," + rightIndex] = value;
    }
    return pairs;
  }
  function parseMacKernTable(p) {
    var pairs = {};
    p.skip("uShort");
    var nTables = p.parseULong();
    if (nTables > 1) {
      console.warn("Only the first kern subtable is supported.");
    }
    p.skip("uLong");
    var coverage = p.parseUShort();
    var subtableVersion = coverage & 255;
    p.skip("uShort");
    if (subtableVersion === 0) {
      var nPairs = p.parseUShort();
      p.skip("uShort", 3);
      for (var i = 0; i < nPairs; i += 1) {
        var leftIndex = p.parseUShort();
        var rightIndex = p.parseUShort();
        var value = p.parseShort();
        pairs[leftIndex + "," + rightIndex] = value;
      }
    }
    return pairs;
  }
  function parseKernTable(data, start) {
    var p = new parse.Parser(data, start);
    var tableVersion = p.parseUShort();
    if (tableVersion === 0) {
      return parseWindowsKernTable(p);
    } else if (tableVersion === 1) {
      return parseMacKernTable(p);
    } else {
      throw new Error("Unsupported kern table version (" + tableVersion + ").");
    }
  }
  var kern = { parse: parseKernTable };
  function parseLocaTable(data, start, numGlyphs, shortVersion) {
    var p = new parse.Parser(data, start);
    var parseFn = shortVersion ? p.parseUShort : p.parseULong;
    var glyphOffsets = [];
    for (var i = 0; i < numGlyphs + 1; i += 1) {
      var glyphOffset = parseFn.call(p);
      if (shortVersion) {
        glyphOffset *= 2;
      }
      glyphOffsets.push(glyphOffset);
    }
    return glyphOffsets;
  }
  var loca = { parse: parseLocaTable };
  function parseOpenTypeTableEntries(data, numTables) {
    var tableEntries = [];
    var p = 12;
    for (var i = 0; i < numTables; i += 1) {
      var tag = parse.getTag(data, p);
      var checksum = parse.getULong(data, p + 4);
      var offset = parse.getULong(data, p + 8);
      var length = parse.getULong(data, p + 12);
      tableEntries.push({ tag, checksum, offset, length, compression: false });
      p += 16;
    }
    return tableEntries;
  }
  function parseWOFFTableEntries(data, numTables) {
    var tableEntries = [];
    var p = 44;
    for (var i = 0; i < numTables; i += 1) {
      var tag = parse.getTag(data, p);
      var offset = parse.getULong(data, p + 4);
      var compLength = parse.getULong(data, p + 8);
      var origLength = parse.getULong(data, p + 12);
      var compression = void 0;
      if (compLength < origLength) {
        compression = "WOFF";
      } else {
        compression = false;
      }
      tableEntries.push({
        tag,
        offset,
        compression,
        compressedLength: compLength,
        length: origLength
      });
      p += 20;
    }
    return tableEntries;
  }
  function uncompressTable(data, tableEntry) {
    if (tableEntry.compression === "WOFF") {
      var inBuffer = new Uint8Array(data.buffer, tableEntry.offset + 2, tableEntry.compressedLength - 2);
      var outBuffer = new Uint8Array(tableEntry.length);
      tinyInflate(inBuffer, outBuffer);
      if (outBuffer.byteLength !== tableEntry.length) {
        throw new Error("Decompression error: " + tableEntry.tag + " decompressed length doesn't match recorded length");
      }
      var view = new DataView(outBuffer.buffer, 0);
      return { data: view, offset: 0 };
    } else {
      return { data, offset: tableEntry.offset };
    }
  }
  function parseBuffer(buffer, opt) {
    opt = opt === void 0 || opt === null ? {} : opt;
    var indexToLocFormat;
    var ltagTable;
    var font = new Font({ empty: true });
    var data = new DataView(buffer, 0);
    var numTables;
    var tableEntries = [];
    var signature = parse.getTag(data, 0);
    if (signature === String.fromCharCode(0, 1, 0, 0) || signature === "true" || signature === "typ1") {
      font.outlinesFormat = "truetype";
      numTables = parse.getUShort(data, 4);
      tableEntries = parseOpenTypeTableEntries(data, numTables);
    } else if (signature === "OTTO") {
      font.outlinesFormat = "cff";
      numTables = parse.getUShort(data, 4);
      tableEntries = parseOpenTypeTableEntries(data, numTables);
    } else if (signature === "wOFF") {
      var flavor = parse.getTag(data, 4);
      if (flavor === String.fromCharCode(0, 1, 0, 0)) {
        font.outlinesFormat = "truetype";
      } else if (flavor === "OTTO") {
        font.outlinesFormat = "cff";
      } else {
        throw new Error("Unsupported OpenType flavor " + signature);
      }
      numTables = parse.getUShort(data, 12);
      tableEntries = parseWOFFTableEntries(data, numTables);
    } else {
      throw new Error("Unsupported OpenType signature " + signature);
    }
    var cffTableEntry;
    var fvarTableEntry;
    var glyfTableEntry;
    var gdefTableEntry;
    var gposTableEntry;
    var gsubTableEntry;
    var hmtxTableEntry;
    var kernTableEntry;
    var locaTableEntry;
    var nameTableEntry;
    var metaTableEntry;
    var p;
    for (var i = 0; i < numTables; i += 1) {
      var tableEntry = tableEntries[i];
      var table2 = void 0;
      switch (tableEntry.tag) {
        case "cmap":
          table2 = uncompressTable(data, tableEntry);
          font.tables.cmap = cmap.parse(table2.data, table2.offset);
          font.encoding = new CmapEncoding(font.tables.cmap);
          break;
        case "cvt ":
          table2 = uncompressTable(data, tableEntry);
          p = new parse.Parser(table2.data, table2.offset);
          font.tables.cvt = p.parseShortList(tableEntry.length / 2);
          break;
        case "fvar":
          fvarTableEntry = tableEntry;
          break;
        case "fpgm":
          table2 = uncompressTable(data, tableEntry);
          p = new parse.Parser(table2.data, table2.offset);
          font.tables.fpgm = p.parseByteList(tableEntry.length);
          break;
        case "head":
          table2 = uncompressTable(data, tableEntry);
          font.tables.head = head.parse(table2.data, table2.offset);
          font.unitsPerEm = font.tables.head.unitsPerEm;
          indexToLocFormat = font.tables.head.indexToLocFormat;
          break;
        case "hhea":
          table2 = uncompressTable(data, tableEntry);
          font.tables.hhea = hhea.parse(table2.data, table2.offset);
          font.ascender = font.tables.hhea.ascender;
          font.descender = font.tables.hhea.descender;
          font.numberOfHMetrics = font.tables.hhea.numberOfHMetrics;
          break;
        case "hmtx":
          hmtxTableEntry = tableEntry;
          break;
        case "ltag":
          table2 = uncompressTable(data, tableEntry);
          ltagTable = ltag.parse(table2.data, table2.offset);
          break;
        case "maxp":
          table2 = uncompressTable(data, tableEntry);
          font.tables.maxp = maxp.parse(table2.data, table2.offset);
          font.numGlyphs = font.tables.maxp.numGlyphs;
          break;
        case "name":
          nameTableEntry = tableEntry;
          break;
        case "OS/2":
          table2 = uncompressTable(data, tableEntry);
          font.tables.os2 = os2.parse(table2.data, table2.offset);
          break;
        case "post":
          table2 = uncompressTable(data, tableEntry);
          font.tables.post = post.parse(table2.data, table2.offset);
          font.glyphNames = new GlyphNames(font.tables.post);
          break;
        case "prep":
          table2 = uncompressTable(data, tableEntry);
          p = new parse.Parser(table2.data, table2.offset);
          font.tables.prep = p.parseByteList(tableEntry.length);
          break;
        case "glyf":
          glyfTableEntry = tableEntry;
          break;
        case "loca":
          locaTableEntry = tableEntry;
          break;
        case "CFF ":
          cffTableEntry = tableEntry;
          break;
        case "kern":
          kernTableEntry = tableEntry;
          break;
        case "GDEF":
          gdefTableEntry = tableEntry;
          break;
        case "GPOS":
          gposTableEntry = tableEntry;
          break;
        case "GSUB":
          gsubTableEntry = tableEntry;
          break;
        case "meta":
          metaTableEntry = tableEntry;
          break;
      }
    }
    var nameTable = uncompressTable(data, nameTableEntry);
    font.tables.name = _name.parse(nameTable.data, nameTable.offset, ltagTable);
    font.names = font.tables.name;
    if (glyfTableEntry && locaTableEntry) {
      var shortVersion = indexToLocFormat === 0;
      var locaTable = uncompressTable(data, locaTableEntry);
      var locaOffsets = loca.parse(locaTable.data, locaTable.offset, font.numGlyphs, shortVersion);
      var glyfTable = uncompressTable(data, glyfTableEntry);
      font.glyphs = glyf.parse(glyfTable.data, glyfTable.offset, locaOffsets, font, opt);
    } else if (cffTableEntry) {
      var cffTable = uncompressTable(data, cffTableEntry);
      cff.parse(cffTable.data, cffTable.offset, font, opt);
    } else {
      throw new Error("Font doesn't contain TrueType or CFF outlines.");
    }
    var hmtxTable = uncompressTable(data, hmtxTableEntry);
    hmtx.parse(font, hmtxTable.data, hmtxTable.offset, font.numberOfHMetrics, font.numGlyphs, font.glyphs, opt);
    addGlyphNames(font, opt);
    if (kernTableEntry) {
      var kernTable = uncompressTable(data, kernTableEntry);
      font.kerningPairs = kern.parse(kernTable.data, kernTable.offset);
    } else {
      font.kerningPairs = {};
    }
    if (gdefTableEntry) {
      var gdefTable = uncompressTable(data, gdefTableEntry);
      font.tables.gdef = gdef.parse(gdefTable.data, gdefTable.offset);
    }
    if (gposTableEntry) {
      var gposTable = uncompressTable(data, gposTableEntry);
      font.tables.gpos = gpos.parse(gposTable.data, gposTable.offset);
      font.position.init();
    }
    if (gsubTableEntry) {
      var gsubTable = uncompressTable(data, gsubTableEntry);
      font.tables.gsub = gsub.parse(gsubTable.data, gsubTable.offset);
    }
    if (fvarTableEntry) {
      var fvarTable = uncompressTable(data, fvarTableEntry);
      font.tables.fvar = fvar.parse(fvarTable.data, fvarTable.offset, font.names);
    }
    if (metaTableEntry) {
      var metaTable = uncompressTable(data, metaTableEntry);
      font.tables.meta = meta.parse(metaTable.data, metaTable.offset);
      font.metas = font.tables.meta;
    }
    return font;
  }
  function loadSync(url, opt) {
    var fs2 = require_fs();
    var buffer = fs2.readFileSync(url);
    return parseBuffer(nodeBufferToArrayBuffer(buffer), opt);
  }

  // src/svg-layout.ts
  var isBrowser2 = typeof window !== "undefined";
  var fs;
  var path;
  if (!isBrowser2) {
    try {
      fs = __require("fs");
      path = __require("path");
    } catch (e) {
    }
  }
  var COLORS = {
    // Backgrounds
    bgPrimary: "#ffffff",
    bgSecondary: "#f8f9fa",
    bgTertiary: "#f1f3f4",
    // Borders
    borderLight: "#e1e4e8",
    borderMedium: "#d0d7de",
    borderDark: "#b0b8c1",
    // Text
    textPrimary: "#1f2328",
    textSecondary: "#57606a",
    textMuted: "#8b949e",
    // Role colors
    systemBorder: "#0969da",
    systemBg: "#f0f7ff",
    systemText: "#0550ae",
    assistantBorder: "#1acad1",
    assistantBg: "#e6fafa",
    assistantText: "#0a9196",
    toolBorder: "#f7660b",
    toolBg: "#ffebe6",
    toolText: "#800d00",
    userBorder: "#e5990b",
    userBg: "#fff8e6",
    userText: "#805600",
    noneBorder: "#6e7781",
    noneBg: "#f5f5f5",
    noneText: "#57606a",
    // Control flow
    controlBg: "#f6f8fa",
    controlBorder: "#6e7781",
    controlText: "#57606a",
    controlHeaderBg: "#eaeef2",
    // Accents
    template: "#9333ea",
    templateBg: "#faf5ff",
    func: "#9333ea",
    funcBg: "#faf5ff",
    context: "#0da66b",
    contextBg: "#e0ffdd",
    variable: "#0969da",
    variableBg: "rgba(9, 105, 218, 0.12)",
    nameRef: "#ec4899",
    comment: "#6e7781",
    string: "#a31515",
    // Fragment badge colors
    badgeBg: "#e5e7eb",
    badgeText: "#4b5563"
  };
  var FONT_SIZES = {
    title: 10,
    normal: 9,
    header: 7,
    comment: 7,
    roleHeader: 7
  };
  var SPACING = {
    containerPaddingLeft: 10,
    containerBorderWidth: 1,
    rolePadding: 6,
    roleBodyPadding: 2,
    blockPadding: 3,
    inlinePadding: 2,
    lineHeight: 1.5,
    elementGap: 3,
    blockGap: 4,
    indentSize: 8
  };
  var regularFont = null;
  var boldFont = null;
  var fontsLoaded = false;
  function loadFonts() {
    if (fontsLoaded) return;
    fontsLoaded = true;
    if (isBrowser2 || !fs || !path) {
      return;
    }
    try {
      const fontsDir = path.join(__dirname, "..", "fonts");
      const regularPath = path.join(fontsDir, "JetBrainsMono-Regular.ttf");
      const boldPath = path.join(fontsDir, "JetBrainsMono-Bold.ttf");
      if (fs.existsSync(regularPath)) {
        regularFont = loadSync(regularPath);
      }
      if (fs.existsSync(boldPath)) {
        boldFont = loadSync(boldPath);
      }
    } catch (e) {
    }
  }
  function getFontBase64(fontType) {
    if (isBrowser2 || !fs || !path) {
      return "";
    }
    try {
      const fontsDir = path.join(__dirname, "..", "fonts");
      const fontPath = path.join(fontsDir, fontType === "bold" ? "JetBrainsMono-Bold.ttf" : "JetBrainsMono-Regular.ttf");
      if (fs.existsSync(fontPath)) {
        const fontData = fs.readFileSync(fontPath);
        return fontData.toString("base64");
      }
    } catch (e) {
    }
    return "";
  }
  function measureText(text, fontSize, bold = false) {
    loadFonts();
    const font = bold ? boldFont : regularFont;
    if (!font) {
      const charWidth = fontSize * 0.55;
      return text.length * charWidth;
    }
    const scale = fontSize / font.unitsPerEm;
    let width = 0;
    for (let i = 0; i < text.length; i++) {
      const glyph = font.charToGlyph(text[i]);
      width += glyph.advanceWidth || 0;
    }
    return width * scale;
  }
  function getLineHeight(fontSize) {
    return fontSize * SPACING.lineHeight;
  }
  function escapeXml(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function svgRect(x, y, width, height, options = {}) {
    const attrs = [
      `x="${x}"`,
      `y="${y}"`,
      `width="${width}"`,
      `height="${height}"`
    ];
    if (options.fill) attrs.push(`fill="${options.fill}"`);
    if (options.stroke) attrs.push(`stroke="${options.stroke}"`);
    if (options.strokeWidth) attrs.push(`stroke-width="${options.strokeWidth}"`);
    if (options.rx) attrs.push(`rx="${options.rx}"`);
    if (options.ry) attrs.push(`ry="${options.ry}"`);
    return `<rect ${attrs.join(" ")}/>`;
  }
  function svgText(x, y, text, options = {}) {
    const fontSize = options.fontSize || FONT_SIZES.normal;
    const fontFamily = options.fontFamily || "'JetBrains Mono', 'SF Mono', monospace";
    const fill = options.fill || COLORS.textPrimary;
    const attrs = [
      `x="${x}"`,
      `y="${y}"`,
      `font-family="${fontFamily}"`,
      `font-size="${fontSize}"`,
      `fill="${fill}"`,
      `text-rendering="geometricPrecision"`
    ];
    if (options.fontWeight) attrs.push(`font-weight="${options.fontWeight}"`);
    if (options.fontStyle) attrs.push(`font-style="${options.fontStyle}"`);
    return `<text ${attrs.join(" ")}>${escapeXml(text)}</text>`;
  }
  function svgLine(x1, y1, x2, y2, options = {}) {
    const attrs = [
      `x1="${x1}"`,
      `y1="${y1}"`,
      `x2="${x2}"`,
      `y2="${y2}"`
    ];
    if (options.stroke) attrs.push(`stroke="${options.stroke}"`);
    if (options.strokeWidth) attrs.push(`stroke-width="${options.strokeWidth}"`);
    if (options.strokeDasharray) attrs.push(`stroke-dasharray="${options.strokeDasharray}"`);
    return `<line ${attrs.join(" ")}/>`;
  }
  function getSvgFontFaces() {
    const regularBase64 = getFontBase64("regular");
    const boldBase64 = getFontBase64("bold");
    let defs = "";
    if (regularBase64) {
      defs += `
      @font-face {
        font-family: 'JetBrains Mono';
        font-weight: 400;
        src: url(data:font/truetype;base64,${regularBase64}) format('truetype');
      }`;
    }
    if (boldBase64) {
      defs += `
      @font-face {
        font-family: 'JetBrains Mono';
        font-weight: 700;
        src: url(data:font/truetype;base64,${boldBase64}) format('truetype');
      }`;
    }
    return defs;
  }
  function wrapSvg(content, width, height) {
    const fontFaces = getSvgFontFaces();
    return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <defs>
    <style type="text/css">
      ${fontFaces}
    </style>
  </defs>
  <rect width="100%" height="100%" fill="${COLORS.bgPrimary}"/>
  ${content}
</svg>`;
  }

  // src/renderPromptSvg.ts
  function isInlineBlock(_kind) {
    return false;
  }
  function renderInlineBlocksWithWrap(blocks, startX, startY, maxWidth, renderBlock) {
    const elements = [];
    const lineHeight = getLineHeight(FONT_SIZES.normal);
    const gap = SPACING.elementGap;
    let currentX = startX;
    let currentY = startY;
    let lineMaxHeight = lineHeight;
    let maxLineWidth = 0;
    for (const block of blocks) {
      const adjustedMaxWidth = maxWidth - currentX;
      const result = renderBlock(block, 0, 0, adjustedMaxWidth);
      if (currentX > startX && currentX + result.width > maxWidth) {
        maxLineWidth = Math.max(maxLineWidth, currentX - startX);
        currentX = startX;
        currentY += lineMaxHeight + gap;
        lineMaxHeight = lineHeight;
        const newAdjustedMaxWidth = maxWidth - currentX;
        const newResult = renderBlock(block, 0, 0, newAdjustedMaxWidth);
        const translated = `<g transform="translate(${currentX}, ${currentY})">${newResult.svg}</g>`;
        elements.push(translated);
        currentX += newResult.width + gap;
        lineMaxHeight = Math.max(lineMaxHeight, newResult.height);
      } else {
        const translated = `<g transform="translate(${currentX}, ${currentY})">${result.svg}</g>`;
        elements.push(translated);
        currentX += result.width + gap;
        lineMaxHeight = Math.max(lineMaxHeight, result.height);
      }
    }
    maxLineWidth = Math.max(maxLineWidth, currentX - startX);
    return {
      svg: elements.join("\n"),
      width: maxLineWidth,
      height: currentY - startY + lineMaxHeight
    };
  }
  function addInlineComment(result, comment, x, y, maxWidth) {
    if (!comment) return result;
    const fontSize = FONT_SIZES.comment;
    const commentText = ` // ${comment}`;
    const commentX = x + result.width + 4;
    const commentWidth = measureText(commentText, fontSize);
    if (maxWidth) {
      const availableWidth = maxWidth - commentX;
      if (availableWidth > 0 && commentWidth > availableWidth) {
        const lines = wrapText(commentText, fontSize, availableWidth, false);
        if (lines.length > 1) {
          const commentY2 = y;
          const wrappedResult = renderMultilineText(lines, commentX, commentY2, {
            fill: COLORS.comment,
            fontSize,
            fontStyle: "italic"
          });
          return {
            svg: result.svg + "\n" + wrappedResult.svg,
            width: result.width + 4 + wrappedResult.width,
            height: Math.max(result.height, wrappedResult.height)
          };
        }
      }
    }
    const commentY = y + result.height / 2 + fontSize * 0.35;
    const commentSvg = svgText(commentX, commentY, commentText, {
      fill: COLORS.comment,
      fontSize,
      fontStyle: "italic"
    });
    return {
      svg: result.svg + "\n" + commentSvg,
      width: result.width + 4 + commentWidth,
      height: result.height
    };
  }
  function wrapText(text, fontSize, maxWidth, bold = false) {
    const words = text.split(/(\s+)/);
    const lines = [];
    let currentLine = "";
    for (const word of words) {
      const testLine = currentLine + word;
      const testWidth = measureText(testLine, fontSize, bold);
      if (testWidth > maxWidth && currentLine.trim() !== "") {
        lines.push(currentLine.trimEnd());
        currentLine = word.trimStart();
      } else {
        currentLine = testLine;
      }
    }
    if (currentLine.trim() !== "") {
      lines.push(currentLine.trimEnd());
    }
    return lines.length > 0 ? lines : [""];
  }
  function renderMultilineText(lines, x, y, options) {
    const lineHeight = getLineHeight(options.fontSize);
    const elements = [];
    let maxWidth = 0;
    for (let i = 0; i < lines.length; i++) {
      const lineY = y + i * lineHeight + options.fontSize * 0.85;
      elements.push(svgText(x, lineY, lines[i], {
        fill: options.fill,
        fontSize: options.fontSize,
        fontWeight: options.fontWeight,
        fontStyle: options.fontStyle
      }));
      maxWidth = Math.max(maxWidth, measureText(lines[i], options.fontSize, options.fontWeight === "700"));
    }
    return {
      svg: elements.join("\n"),
      width: maxWidth,
      height: lines.length * lineHeight
    };
  }
  function getRoleColors(role) {
    switch (role.toLowerCase()) {
      case "system":
        return { border: COLORS.systemBorder, bg: COLORS.systemBorder, text: "#ffffff" };
      case "user":
        return { border: COLORS.userBorder, bg: COLORS.userBorder, text: "#ffffff" };
      case "assistant":
        return { border: COLORS.assistantBorder, bg: COLORS.assistantBorder, text: "#ffffff" };
      case "tool":
        return { border: COLORS.toolBorder, bg: COLORS.toolBorder, text: "#ffffff" };
      default:
        return { border: COLORS.noneBorder, bg: COLORS.noneBorder, text: "#ffffff" };
    }
  }
  function renderInlineBox(text, x, y, options) {
    const fontSize = FONT_SIZES.normal;
    const padding = options.nested ? 2 : SPACING.blockPadding;
    const prefixText = options.prefix || "";
    const isDiamond = prefixText.includes("\u25C6");
    const diamondSize = fontSize * 0.6;
    const diamondSpacing = 2;
    const prefixWidth = isDiamond ? diamondSize + diamondSpacing : prefixText ? measureText(prefixText, fontSize * 0.7, true) : 0;
    const textWidthOnly = measureText(text, fontSize, options.bold);
    const totalTextWidth = prefixWidth + textWidthOnly;
    const boxWidth = totalTextWidth + padding * 2;
    const boxHeight = fontSize + padding * 2;
    const elements = [];
    elements.push(svgRect(x, y, boxWidth, boxHeight, {
      fill: options.fill,
      stroke: options.stroke,
      strokeWidth: 1,
      rx: 3
    }));
    const textY = y + padding + fontSize * 0.85;
    let textX = x + padding;
    if (isDiamond) {
      const cx = textX + diamondSize / 2;
      const cy = y + boxHeight / 2;
      const size = diamondSize * 0.6;
      elements.push(`<rect x="${cx - size / 2}" y="${cy - size / 2}" width="${size}" height="${size}" fill="${options.textColor}" transform="rotate(45 ${cx} ${cy})" />`);
      textX += prefixWidth;
    } else if (prefixText) {
      elements.push(svgText(textX, textY, prefixText, {
        fill: options.textColor,
        fontSize: fontSize * 0.7,
        fontWeight: "600"
      }));
      textX += prefixWidth;
    }
    elements.push(svgText(textX, textY, text, {
      fill: options.textColor,
      fontSize,
      fontWeight: options.bold ? "550" : "550"
    }));
    return {
      svg: elements.join("\n"),
      width: boxWidth,
      height: boxHeight
    };
  }
  function renderStyledText(text, x, y, options = {}) {
    const fontSize = options.fontSize || FONT_SIZES.normal;
    const width = measureText(text, fontSize, options.bold);
    const svg = svgText(x, y, text, {
      fill: options.color || COLORS.textPrimary,
      fontSize,
      fontWeight: options.bold ? "550" : "550",
      fontStyle: options.italic ? "italic" : void 0
    });
    return { svg, width, height: fontSize };
  }
  function indexToText(index) {
    const content = indexValueToText(index.value);
    if (index.kind === "time-index") {
      return `@${content}`;
    }
    return content;
  }
  function indexValueToText(value) {
    switch (value.kind) {
      case "identifier":
        let result = value.name;
        if (value.path) {
          result += "." + pathToText(value.path);
        }
        return result;
      case "context-var":
        return contextVarToText(value);
      case "function":
        return funcToText(value);
      case "arithmetic":
        return `${indexValueToText(value.left)}${value.operator.join("")}${indexValueToText(value.right)}`;
      case "name-ref":
        return value.name;
    }
  }
  function pathToText(path2) {
    let result = path2.base;
    if (path2.indices.length > 0) {
      result += "[" + path2.indices.map(indexToText).join(",") + "]";
    }
    if (path2.next) {
      result += "." + pathToText(path2.next);
    }
    return result;
  }
  function contextVarToText(cv) {
    let result = cv.base;
    if (cv.indices.length > 0) {
      result += "[" + cv.indices.map(indexToText).join(",") + "]";
    }
    if (cv.path) {
      result += "." + pathToText(cv.path);
    }
    return result;
  }
  function funcToText(func2) {
    const args = func2.arguments.map(textArgsToText).join(", ");
    return `${func2.name}(${args})`;
  }
  function textArgsToText(arg) {
    switch (arg.kind) {
      case "context-var":
        return contextVarToText(arg);
      case "function":
        return funcToText(arg);
      case "time-index":
      case "other-index":
        return indexToText(arg);
      case "identifier":
        let result = arg.name;
        if (arg.path) {
          result += "." + pathToText(arg.path);
        }
        return result;
      case "arithmetic":
        return `${textArgsToText(arg.left)}${arg.operator.join("")}${textArgsToText(arg.right)}`;
      case "name-ref":
        return nameRefToText(arg);
      case "str-frag-invocation":
        const fragArgs = arg.arguments.map(textArgsToText).join(", ");
        return `Frag ${arg.name}[${fragArgs}]`;
    }
  }
  function stripNameRefPrefix(name) {
    return name.startsWith("$") ? name.slice(1) : name;
  }
  function nameRefToText(ref) {
    let result = stripNameRefPrefix(ref.name);
    if (ref.indices.length > 0) {
      result += "[" + ref.indices.map(indexToText).join(",") + "]";
    }
    if (ref.path) {
      result += "." + pathToText(ref.path);
    }
    return result;
  }
  function renderTemplateBlock2(block, x, y, maxWidth) {
    if (block.arguments.length === 0) {
      const text = block.name;
      const result2 = renderInlineBox(text, x, y, {
        fill: COLORS.templateBg,
        stroke: COLORS.template,
        textColor: COLORS.template,
        prefix: "\u25C6 "
      });
      return addInlineComment(result2, block.comment, x, y, maxWidth);
    }
    const elements = [];
    const fontSize = FONT_SIZES.normal;
    const padding = SPACING.blockPadding;
    const lineHeight = getLineHeight(fontSize);
    const nestedPadding = 2;
    const nestedYOffset = padding - nestedPadding;
    let currentX = x + padding;
    let currentY = y;
    const startX = x + padding;
    const textY = y + padding + fontSize * 0.85;
    let maxRenderedWidth = 0;
    let totalHeight = fontSize + padding * 2;
    const diamondSize = fontSize * 0.6;
    const diamondSpacing = 2;
    const boxHeight = fontSize + padding * 2;
    const cx = currentX + diamondSize / 2;
    const cy = y + boxHeight / 2;
    const size = diamondSize * 0.6;
    elements.push(`<rect x="${cx - size / 2}" y="${cy - size / 2}" width="${size}" height="${size}" fill="${COLORS.template}" transform="rotate(45 ${cx} ${cy})" />`);
    currentX += diamondSize + diamondSpacing;
    elements.push(svgText(currentX, textY, block.name, {
      fill: COLORS.template,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText(block.name, fontSize, true);
    elements.push(svgText(currentX, textY, "(", {
      fill: COLORS.template,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText("(", fontSize, true);
    const indentX = startX + measureText("  ", fontSize);
    for (let i = 0; i < block.arguments.length; i++) {
      const argResult = renderTextArgsElement(block.arguments[i], 0, 0, true);
      const currentTextY = currentY + padding + fontSize * 0.85;
      const translatedArg = `<g transform="translate(${currentX}, ${currentY + nestedYOffset})">${argResult.svg}</g>`;
      elements.push(translatedArg);
      currentX += argResult.width;
      if (i < block.arguments.length - 1) {
        elements.push(svgText(currentX, currentTextY, ",", {
          fill: COLORS.template,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(",", fontSize, true);
        maxRenderedWidth = Math.max(maxRenderedWidth, currentX - x + padding);
        const nextArgResult = renderTextArgsElement(block.arguments[i + 1], 0, 0, true);
        const spaceWidth = measureText(" ", fontSize);
        const availableWidth = maxWidth ? maxWidth - currentX - spaceWidth : Infinity;
        const shouldWrap = maxWidth && nextArgResult.width > availableWidth;
        if (shouldWrap) {
          currentY += lineHeight;
          currentX = indentX;
        } else {
          currentX += spaceWidth;
        }
      } else {
        maxRenderedWidth = Math.max(maxRenderedWidth, currentX - x + padding);
      }
      totalHeight = Math.max(totalHeight, currentY - y + argResult.height + padding);
    }
    const closingTextY = currentY + padding + fontSize * 0.85;
    elements.push(svgText(currentX, closingTextY, ")", {
      fill: COLORS.template,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText(")", fontSize, true);
    const boxWidth = Math.max(maxRenderedWidth, currentX - x + padding);
    const bgRect = svgRect(x, y, boxWidth, totalHeight, {
      fill: COLORS.templateBg,
      stroke: COLORS.template,
      strokeWidth: 1,
      rx: 3
    });
    const result = {
      svg: bgRect + "\n" + elements.join("\n"),
      width: boxWidth,
      height: totalHeight
    };
    return addInlineComment(result, block.comment, x, y, maxWidth);
  }
  function textArgsToColoredSegments(arg) {
    const segments = [];
    switch (arg.kind) {
      case "context-var":
        return contextVarToColoredSegments(arg);
      case "function":
        return funcToColoredSegments(arg);
      case "time-index":
      case "other-index":
        segments.push({ text: indexToText(arg), type: "index" });
        break;
      case "identifier":
        segments.push({ text: arg.name, type: "default" });
        if (arg.path) {
          segments.push(...pathToColoredSegments(arg.path));
        }
        break;
      case "arithmetic":
        segments.push(...textArgsToColoredSegments(arg.left));
        segments.push({ text: arg.operator.join(""), type: "default" });
        segments.push(...textArgsToColoredSegments(arg.right));
        break;
      case "name-ref":
        segments.push({ text: nameRefToText(arg), type: "nameRef" });
        break;
    }
    return segments;
  }
  function pathToColoredSegments(path2) {
    const segments = [];
    segments.push({ text: ".", type: "default" });
    segments.push({ text: path2.base, type: "default" });
    if (path2.indices.length > 0) {
      segments.push({ text: "[", type: "default" });
      for (let i = 0; i < path2.indices.length; i++) {
        if (i > 0) segments.push({ text: ",", type: "default" });
        segments.push({ text: indexToText(path2.indices[i]), type: "index" });
      }
      segments.push({ text: "]", type: "default" });
    }
    if (path2.next) {
      segments.push(...pathToColoredSegments(path2.next));
    }
    return segments;
  }
  function funcToColoredSegments(block) {
    const segments = [];
    segments.push({ text: block.name, type: "default" });
    segments.push({ text: "(", type: "default" });
    for (let i = 0; i < block.arguments.length; i++) {
      if (i > 0) segments.push({ text: ", ", type: "default" });
      segments.push(...textArgsToColoredSegments(block.arguments[i]));
    }
    segments.push({ text: ")", type: "default" });
    if (block.indices && block.indices.length > 0) {
      segments.push({ text: "[", type: "default" });
      for (let i = 0; i < block.indices.length; i++) {
        if (i > 0) segments.push({ text: ",", type: "default" });
        segments.push({ text: indexToText(block.indices[i]), type: "index" });
      }
      segments.push({ text: "]", type: "default" });
    }
    return segments;
  }
  function renderTextArgsElement(arg, x, y, nested = false) {
    switch (arg.kind) {
      case "context-var":
        return renderContextVarBoxed(arg, x, y, nested);
      case "function":
        return renderFuncBlock2(arg, x, y, nested);
      case "time-index":
      case "other-index":
        return renderIndex(arg, x, y, nested);
      case "identifier":
        return renderIdentifierBoxed(arg, x, y, nested);
      case "arithmetic":
        return renderArithmeticBoxed(arg, x, y, nested);
      case "name-ref":
        return renderNameRef2(arg, x, y, nested);
      case "str-frag-invocation":
        return renderStrFragInvocation2(arg, x, y);
    }
  }
  function renderContextVarBoxed(block, x, y, nested = false) {
    const segments = contextVarToColoredSegments(block);
    return renderColoredSegmentBox(segments, x, y, {
      fill: COLORS.contextBg,
      stroke: COLORS.context,
      defaultColor: COLORS.context,
      nested
    });
  }
  function renderIndex(index, x, y, nested = false) {
    const text = indexToText(index);
    const fontSize = FONT_SIZES.normal;
    const padding = nested ? 2 : SPACING.blockPadding;
    const textY = y + padding + fontSize * 0.85;
    const svg = svgText(x, textY, text, {
      fill: COLORS.variable,
      fontSize,
      fontWeight: "700"
    });
    return {
      svg,
      width: measureText(text, fontSize, true),
      height: fontSize + padding * 2
    };
  }
  function renderIdentifierBoxed(arg, x, y, nested = false) {
    const segments = [];
    segments.push({ text: arg.name, type: "default" });
    if (arg.path) {
      segments.push(...pathToColoredSegments(arg.path));
    }
    const text = segments.map((s) => s.text).join("");
    const padding = nested ? 2 : SPACING.blockPadding;
    return renderStyledText(text, x, y + padding + FONT_SIZES.normal * 0.85, {
      color: COLORS.textPrimary,
      fontSize: FONT_SIZES.normal
    });
  }
  function renderArithmeticBoxed(arg, x, y, nested = false) {
    const elements = [];
    let currentX = x;
    const fontSize = FONT_SIZES.normal;
    const padding = nested ? 2 : SPACING.blockPadding;
    const leftResult = renderTextArgsElement(arg.left, currentX, y, nested);
    elements.push(leftResult.svg);
    currentX += leftResult.width;
    const opText = arg.operator.join("");
    elements.push(svgText(currentX, y + padding + fontSize * 0.85, opText, {
      fill: COLORS.textPrimary,
      fontSize
    }));
    currentX += measureText(opText, fontSize);
    const rightResult = renderTextArgsElement(arg.right, currentX, y, nested);
    elements.push(rightResult.svg);
    currentX += rightResult.width;
    return {
      svg: elements.join("\n"),
      width: currentX - x,
      height: Math.max(leftResult.height, rightResult.height, fontSize + padding * 2)
    };
  }
  function nameRefToColoredSegments(ref) {
    const segments = [];
    segments.push({ text: stripNameRefPrefix(ref.name), type: "nameRef" });
    if (ref.indices.length > 0) {
      segments.push({ text: "[", type: "nameRef" });
      for (let i = 0; i < ref.indices.length; i++) {
        if (i > 0) segments.push({ text: ",", type: "nameRef" });
        segments.push({ text: indexToText(ref.indices[i]), type: "index" });
      }
      segments.push({ text: "]", type: "nameRef" });
    }
    if (ref.path) {
      let current = ref.path;
      while (current) {
        segments.push({ text: ".", type: "nameRef" });
        segments.push({ text: current.base, type: "nameRef" });
        if (current.indices.length > 0) {
          segments.push({ text: "[", type: "nameRef" });
          for (let i = 0; i < current.indices.length; i++) {
            if (i > 0) segments.push({ text: ",", type: "nameRef" });
            segments.push({ text: indexToText(current.indices[i]), type: "index" });
          }
          segments.push({ text: "]", type: "nameRef" });
        }
        current = current.next;
      }
    }
    return segments;
  }
  function renderNameRef2(ref, x, y, nested = false) {
    const segments = nameRefToColoredSegments(ref);
    const fontSize = FONT_SIZES.normal;
    const padding = nested ? 2 : SPACING.blockPadding;
    const elements = [];
    let currentX = x;
    const textY = y + padding + fontSize * 0.85;
    for (const seg of segments) {
      const color = seg.type === "index" ? COLORS.variable : COLORS.nameRef;
      const fontWeight = "600";
      elements.push(svgText(currentX, textY, seg.text, {
        fill: color,
        fontSize,
        fontWeight
      }));
      currentX += measureText(seg.text, fontSize, true);
    }
    return {
      svg: elements.join("\n"),
      width: currentX - x,
      height: fontSize + padding * 2
    };
  }
  function renderFuncBlock2(block, x, y, nested = false, maxWidth) {
    if (block.name === "range" && block.arguments.length >= 2) {
      const start = textArgsToText(block.arguments[0]);
      const end = textArgsToText(block.arguments[1]);
      const step = block.arguments.length >= 3 ? ` every ${textArgsToText(block.arguments[2])}` : "";
      const text = `${start}...${end}${step}`;
      return renderStyledText(text, x, y + FONT_SIZES.normal * 0.85, {
        color: COLORS.textPrimary,
        fontSize: FONT_SIZES.normal
      });
    }
    if (block.name === "min" || block.name === "max") {
      const segments = funcToColoredSegments(block);
      const text = segments.map((s) => s.text).join("");
      return renderStyledText(text, x, y + FONT_SIZES.normal * 0.85, {
        color: COLORS.textPrimary,
        fontSize: FONT_SIZES.normal
      });
    }
    const elements = [];
    const fontSize = FONT_SIZES.normal;
    const padding = SPACING.blockPadding;
    const lineHeight = getLineHeight(fontSize);
    const nestedPadding = 2;
    const nestedYOffset = padding - nestedPadding;
    let currentX = x + padding;
    let currentY = y;
    const startX = x + padding;
    const textY = y + padding + fontSize * 0.85;
    let maxRenderedWidth = 0;
    let totalHeight = fontSize + padding * 2;
    elements.push(svgText(currentX, textY, block.name, {
      fill: COLORS.func,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText(block.name, fontSize, true);
    elements.push(svgText(currentX, textY, "(", {
      fill: COLORS.func,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText("(", fontSize, true);
    const indentX = startX + measureText("  ", fontSize);
    for (let i = 0; i < block.arguments.length; i++) {
      const argResult = renderTextArgsElement(block.arguments[i], 0, 0, true);
      const currentTextY = currentY + padding + fontSize * 0.85;
      const translatedArg = `<g transform="translate(${currentX}, ${currentY + nestedYOffset})">${argResult.svg}</g>`;
      elements.push(translatedArg);
      currentX += argResult.width;
      if (i < block.arguments.length - 1) {
        elements.push(svgText(currentX, currentTextY, ",", {
          fill: COLORS.func,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(",", fontSize, true);
        maxRenderedWidth = Math.max(maxRenderedWidth, currentX - x + padding);
        const nextArgResult = renderTextArgsElement(block.arguments[i + 1], 0, 0, true);
        const spaceWidth = measureText(" ", fontSize);
        const availableWidth = maxWidth ? maxWidth - currentX - spaceWidth : Infinity;
        const shouldWrap = maxWidth && nextArgResult.width > availableWidth;
        if (shouldWrap) {
          currentY += lineHeight;
          currentX = indentX;
        } else {
          currentX += spaceWidth;
        }
      } else {
        maxRenderedWidth = Math.max(maxRenderedWidth, currentX - x + padding);
      }
      totalHeight = Math.max(totalHeight, currentY - y + argResult.height + padding);
    }
    const closingTextY = currentY + padding + fontSize * 0.85;
    elements.push(svgText(currentX, closingTextY, ")", {
      fill: COLORS.func,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText(")", fontSize, true);
    if (block.indices && block.indices.length > 0) {
      elements.push(svgText(currentX, closingTextY, "[", {
        fill: COLORS.func,
        fontSize,
        fontWeight: "600"
      }));
      currentX += measureText("[", fontSize, true);
      for (let i = 0; i < block.indices.length; i++) {
        if (i > 0) {
          elements.push(svgText(currentX, closingTextY, ",", {
            fill: COLORS.func,
            fontSize
          }));
          currentX += measureText(",", fontSize);
        }
        const idxText = indexToText(block.indices[i]);
        elements.push(svgText(currentX, closingTextY, idxText, {
          fill: COLORS.variable,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(idxText, fontSize, true);
      }
      elements.push(svgText(currentX, closingTextY, "]", {
        fill: COLORS.func,
        fontSize,
        fontWeight: "600"
      }));
      currentX += measureText("]", fontSize, true);
    }
    const boxWidth = Math.max(maxRenderedWidth, currentX - x + padding);
    const bgRect = svgRect(x, y, boxWidth, totalHeight, {
      fill: COLORS.funcBg,
      stroke: COLORS.func,
      strokeWidth: 1,
      rx: 3
    });
    const result = {
      svg: bgRect + "\n" + elements.join("\n"),
      width: boxWidth,
      height: totalHeight
    };
    return addInlineComment(result, block.comment, x, y, maxWidth);
  }
  function renderColoredSegmentBox(segments, x, y, options) {
    const fontSize = FONT_SIZES.normal;
    const padding = options.nested ? 2 : SPACING.blockPadding;
    let totalWidth = 0;
    if (options.prefix) {
      totalWidth += measureText(options.prefix, fontSize, true);
    }
    for (const seg of segments) {
      totalWidth += measureText(seg.text, fontSize, true);
    }
    const boxWidth = totalWidth + padding * 2;
    const boxHeight = fontSize + padding * 2;
    const elements = [];
    elements.push(svgRect(x, y, boxWidth, boxHeight, {
      fill: options.fill,
      stroke: options.stroke,
      strokeWidth: 1,
      rx: 3
    }));
    const textY = y + padding + fontSize * 0.85;
    let textX = x + padding;
    if (options.prefix) {
      elements.push(svgText(textX, textY, options.prefix, {
        fill: options.defaultColor,
        fontSize,
        fontWeight: "600"
      }));
      textX += measureText(options.prefix, fontSize, true);
    }
    for (const seg of segments) {
      let color = options.defaultColor;
      let fontWeight = "600";
      switch (seg.type) {
        case "index":
          color = COLORS.variable;
          fontWeight = "600";
          break;
        case "nameRef":
          color = COLORS.nameRef;
          fontWeight = "600";
          break;
        case "contextVar":
          color = COLORS.context;
          fontWeight = "600";
          break;
        default:
          color = options.defaultColor;
      }
      elements.push(svgText(textX, textY, seg.text, {
        fill: color,
        fontSize,
        fontWeight
      }));
      textX += measureText(seg.text, fontSize, true);
    }
    return {
      svg: elements.join("\n"),
      width: boxWidth,
      height: boxHeight
    };
  }
  function addIndexSegments(segments, index) {
    if (index.kind === "time-index" && index.value.kind === "name-ref") {
      segments.push({ text: "@", type: "index" });
      segments.push({ text: index.value.name, type: "nameRef" });
    } else if (index.value.kind === "name-ref") {
      segments.push({ text: index.value.name, type: "nameRef" });
    } else {
      segments.push({ text: indexToText(index), type: "index" });
    }
  }
  function contextVarToColoredSegments(block) {
    const segments = [];
    segments.push({ text: block.base, type: "contextVar" });
    if (block.indices.length > 0) {
      segments.push({ text: "[", type: "contextVar" });
      for (let i = 0; i < block.indices.length; i++) {
        if (i > 0) segments.push({ text: ",", type: "contextVar" });
        addIndexSegments(segments, block.indices[i]);
      }
      segments.push({ text: "]", type: "contextVar" });
    }
    let current = block.path;
    while (current) {
      segments.push({ text: ".", type: "contextVar" });
      segments.push({ text: current.base, type: "contextVar" });
      if (current.indices.length > 0) {
        segments.push({ text: "[", type: "contextVar" });
        for (let i = 0; i < current.indices.length; i++) {
          if (i > 0) segments.push({ text: ",", type: "contextVar" });
          addIndexSegments(segments, current.indices[i]);
        }
        segments.push({ text: "]", type: "contextVar" });
      }
      current = current.next;
    }
    return segments;
  }
  function renderContextVarBlock2(block, x, y, maxWidth) {
    const segments = contextVarToColoredSegments(block);
    const result = renderColoredSegmentBox(segments, x, y, {
      fill: COLORS.contextBg,
      stroke: COLORS.context,
      defaultColor: COLORS.context
    });
    return addInlineComment(result, block.comment, x, y, maxWidth);
  }
  function renderNameRefBlock(block, x, y) {
    const text = nameRefToText(block);
    return renderStyledText(text, x, y + FONT_SIZES.normal * 0.85, {
      color: COLORS.nameRef,
      fontSize: FONT_SIZES.normal,
      bold: true
    });
  }
  function renderComment(text, x, y, addOffset = false, maxWidth) {
    const commentText = `// ${text}`;
    const contentX = addOffset ? x + 8 : x;
    const fontSize = FONT_SIZES.comment;
    if (maxWidth) {
      const availableWidth = maxWidth - contentX;
      const lines = wrapText(commentText, fontSize, availableWidth, false);
      const result = renderMultilineText(lines, contentX, y, {
        fill: COLORS.comment,
        fontSize,
        fontStyle: "italic"
      });
      return result;
    }
    return renderStyledText(commentText, contentX, y + fontSize * 0.85, {
      color: COLORS.comment,
      fontSize,
      italic: true
    });
  }
  function renderIndexValue2(index, x, y) {
    const text = indexToText(index);
    const color = index.kind === "time-index" ? COLORS.variable : COLORS.variable;
    return renderStyledText(text, x, y + FONT_SIZES.normal * 0.85, {
      color,
      fontSize: FONT_SIZES.normal,
      bold: true
    });
  }
  function renderRoleBuildingBlock2(block, x, y, maxWidth) {
    if (block.kind === "conditional-block-inside-role") {
      console.log("[renderRoleBuildingBlock] calling renderConditionalInsideRole with maxWidth:", maxWidth);
    }
    switch (block.kind) {
      case "template":
        return renderTemplateBlock2(block, x, y, maxWidth);
      case "context-var":
        return renderContextVarBlock2(block, x, y, maxWidth);
      case "function":
        return renderFuncBlock2(block, x, y, false, maxWidth);
      case "name-ref":
        return renderNameRefBlock(block, x, y);
      case "comment-block":
        return renderComment(block.text, x, y, false, maxWidth);
      case "name-def":
        return renderNameDef2(block, x, y, maxWidth);
      case "other-index":
        return renderIndexValue2(block, x, y);
      case "loop-block-inside-role":
        return renderLoopInsideRole2(block, x, y, maxWidth);
      case "conditional-block-inside-role":
        return renderConditionalInsideRole2(block, x, y, maxWidth);
      case "switch-block-inside-role":
        return renderSwitchInsideRole2(block, x, y, maxWidth);
      case "mark-block-inside-role":
        return renderMarkBlockInsideRole2(block, x, y, maxWidth);
      case "end-block":
        return renderEndBlock2(block, x, y);
      case "str-frag-invocation":
        return renderStrFragInvocation2(block, x, y, maxWidth);
      default:
        return { svg: "", width: 0, height: 0 };
    }
  }
  function renderNameDef2(block, x, y, maxWidth) {
    const elements = [];
    const startX = x + 8;
    let currentX = startX;
    const fontSize = FONT_SIZES.normal;
    const padding = SPACING.blockPadding;
    const boxHeight = fontSize + padding * 2;
    const textY = y + padding + fontSize * 0.85;
    elements.push(svgText(currentX, textY, "Name", {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "800"
    }));
    currentX += measureText("Name", fontSize, true) + 4;
    elements.push(svgText(currentX, textY, block.name, {
      fill: COLORS.nameRef,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText(block.name, fontSize, true) + 4;
    elements.push(svgText(currentX, textY, ":=", {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText(":=", fontSize, true) + 4;
    let valueResult;
    if (block.value.kind === "context-var") {
      valueResult = renderContextVarBlock2(block.value, 0, 0, void 0);
    } else if (block.value.kind === "function") {
      valueResult = renderFuncBlock2(block.value, 0, 0, false, void 0);
    } else if (block.value.kind === "list-comprehension") {
      valueResult = renderListComprehension2(block.value, 0, 0, void 0);
    } else {
      valueResult = renderStrFragInvocation2(block.value, 0, 0, void 0);
    }
    const availableWidth = maxWidth ? maxWidth - currentX : Infinity;
    const fitsOnSameLine = valueResult.width <= availableWidth;
    if (fitsOnSameLine) {
      const translated = `<g transform="translate(${currentX}, ${y})">${valueResult.svg}</g>`;
      elements.push(translated);
      currentX += valueResult.width;
      return {
        svg: elements.join("\n"),
        width: currentX - x,
        height: Math.max(boxHeight, valueResult.height)
      };
    } else {
      const lineHeight = getLineHeight(fontSize);
      const nextLineY = y + lineHeight + SPACING.elementGap;
      if (block.value.kind === "context-var") {
        valueResult = renderContextVarBlock2(block.value, 0, 0, void 0);
      } else if (block.value.kind === "function") {
        valueResult = renderFuncBlock2(block.value, 0, 0, false, void 0);
      } else if (block.value.kind === "list-comprehension") {
        valueResult = renderListComprehension2(block.value, 0, 0, void 0);
      } else {
        valueResult = renderStrFragInvocation2(block.value, 0, 0, void 0);
      }
      const translated = `<g transform="translate(${startX}, ${nextLineY})">${valueResult.svg}</g>`;
      elements.push(translated);
      return {
        svg: elements.join("\n"),
        width: Math.max(currentX - x, startX - x + valueResult.width),
        height: lineHeight + SPACING.elementGap + valueResult.height
      };
    }
  }
  function renderListComprehension2(block, x, y, _maxWidth) {
    const elements = [];
    let currentX = x;
    const fontSize = FONT_SIZES.normal;
    const padding = SPACING.blockPadding;
    const textY = y + padding + fontSize * 0.85;
    elements.push(svgText(currentX, textY, "[", {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "700"
    }));
    currentX += measureText("[", fontSize, true) + 2;
    let elemResult;
    if (block.element.kind === "context-var") {
      elemResult = renderContextVarBlock2(block.element, currentX, y);
    } else if (block.element.kind === "function") {
      elemResult = renderFuncBlock2(block.element, currentX, y);
    } else {
      elemResult = renderStrFragInvocation2(block.element, currentX, y);
    }
    elements.push(elemResult.svg);
    currentX += elemResult.width + 4;
    elements.push(svgText(currentX, textY, "|", {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "700"
    }));
    currentX += measureText("|", fontSize, true) + 4;
    elements.push(svgText(currentX, textY, block.variable, {
      fill: COLORS.variable,
      fontSize,
      fontWeight: "700"
    }));
    currentX += measureText(block.variable, fontSize, true) + 4;
    elements.push(svgText(currentX, textY, "\u2208", {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText("\u2208", fontSize) + 4;
    const iterTokens = iterableToTokens(block.iterable);
    const iterResult = renderExpressionTokensSvg(iterTokens, currentX, textY, fontSize);
    elements.push(...iterResult.elements);
    currentX += iterResult.width + 2;
    elements.push(svgText(currentX, textY, "]", {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "700"
    }));
    currentX += measureText("]", fontSize, true);
    return {
      svg: elements.join("\n"),
      width: currentX - x,
      height: Math.max(fontSize + padding * 2, elemResult.height)
    };
  }
  function renderEndBlock2(block, x, y) {
    const elements = [];
    const lineHeight = getLineHeight(FONT_SIZES.normal);
    const fontSize = FONT_SIZES.normal;
    const textY = y + fontSize * 0.85;
    const lineY = textY - fontSize * 0.35;
    const lineStartX = x;
    const dashLength = 80;
    elements.push(svgLine(lineStartX, lineY, lineStartX + dashLength, lineY, {
      stroke: COLORS.textPrimary,
      strokeWidth: 1,
      strokeDasharray: "4,4"
    }));
    let currentX = lineStartX + dashLength + 6;
    elements.push(svgText(currentX, textY, "PromptEndsHere", {
      fill: COLORS.textPrimary,
      fontSize: FONT_SIZES.normal,
      fontWeight: "800"
    }));
    currentX += measureText("PromptEndsHere", FONT_SIZES.normal, true) + 4;
    elements.push(svgText(currentX, textY, "when", {
      fill: COLORS.textPrimary,
      fontSize: FONT_SIZES.normal,
      fontWeight: "800"
    }));
    currentX += measureText("when", FONT_SIZES.normal, true) + 4;
    const condResult = renderExpressionTokensSvg(block.condition, currentX, textY, FONT_SIZES.normal);
    elements.push(...condResult.elements);
    currentX += condResult.width;
    return {
      svg: elements.join("\n"),
      width: currentX - x,
      height: lineHeight
    };
  }
  function renderStrFragDefSvg(frag, x, y, maxWidth) {
    const elements = [];
    const fontSize = FONT_SIZES.title;
    const badgeFontSize = 8;
    let currentY = y;
    let titleText = frag.name;
    if (frag.params.length > 0) {
      const paramsText = frag.params.map((p) => textArgsToText(p)).join(", ");
      titleText += `[${paramsText}]`;
    }
    const titleWidth = measureText(titleText, fontSize);
    elements.push(svgText(x, currentY + fontSize, titleText, {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "700"
    }));
    const badgeText = "SF";
    const badgeTextWidth = measureText(badgeText, badgeFontSize);
    const badgePadding = 4;
    const badgeWidth = badgeTextWidth + badgePadding * 2;
    const badgeHeight = badgeFontSize + badgePadding;
    const badgeX = x + titleWidth + 8;
    const badgeY = currentY + (fontSize - badgeHeight) / 2 + 2;
    elements.push(svgRect(badgeX, badgeY, badgeWidth, badgeHeight, {
      fill: COLORS.badgeBg,
      rx: 3,
      ry: 3
    }));
    elements.push(svgText(badgeX + badgePadding, badgeY + badgeFontSize - 1, badgeText, {
      fill: COLORS.badgeText,
      fontSize: badgeFontSize,
      fontWeight: "600"
    }));
    const titleHeight = fontSize + SPACING.blockGap;
    currentY += titleHeight;
    const borderStartY = currentY;
    const bodyX = x + SPACING.indentSize;
    let bodyHeight = 0;
    for (const block of frag.body) {
      const result = renderRoleBuildingBlock2(block, bodyX, currentY, maxWidth ? maxWidth - SPACING.indentSize : void 0);
      elements.push(result.svg);
      currentY += result.height + SPACING.elementGap;
      bodyHeight += result.height + SPACING.elementGap;
    }
    elements.push(svgLine(x, borderStartY, x, currentY - SPACING.elementGap, {
      stroke: COLORS.borderMedium,
      strokeWidth: 1
    }));
    const totalHeight = titleHeight + bodyHeight;
    const totalWidth = maxWidth || 400;
    return {
      svg: elements.join("\n"),
      width: totalWidth,
      height: totalHeight
    };
  }
  function renderRolesFragDefSvg(frag, x, y, maxWidth) {
    const elements = [];
    const fontSize = FONT_SIZES.title;
    const badgeFontSize = 8;
    let currentY = y;
    let titleText = frag.name;
    if (frag.params.length > 0) {
      const paramsText = frag.params.map((p) => textArgsToText(p)).join(", ");
      titleText += `[${paramsText}]`;
    }
    const titleWidth = measureText(titleText, fontSize);
    elements.push(svgText(x, currentY + fontSize, titleText, {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "700"
    }));
    const badgeText = "RF";
    const badgeTextWidth = measureText(badgeText, badgeFontSize);
    const badgePadding = 4;
    const badgeWidth = badgeTextWidth + badgePadding * 2;
    const badgeHeight = badgeFontSize + badgePadding;
    const badgeX = x + titleWidth + 8;
    const badgeY = currentY + (fontSize - badgeHeight) / 2 + 2;
    elements.push(svgRect(badgeX, badgeY, badgeWidth, badgeHeight, {
      fill: COLORS.badgeBg,
      rx: 3,
      ry: 3
    }));
    elements.push(svgText(badgeX + badgePadding, badgeY + badgeFontSize - 1, badgeText, {
      fill: COLORS.badgeText,
      fontSize: badgeFontSize,
      fontWeight: "600"
    }));
    const titleHeight = fontSize + SPACING.blockGap;
    currentY += titleHeight;
    const borderStartY = currentY;
    let bodyHeight = 0;
    for (const block of frag.body) {
      const result = renderTopLevelBlock2(block, x, currentY, maxWidth);
      elements.push(result.svg);
      currentY += result.height + SPACING.blockGap;
      bodyHeight += result.height + SPACING.blockGap;
    }
    elements.push(svgLine(x, borderStartY, x, currentY - SPACING.blockGap, {
      stroke: COLORS.borderMedium,
      strokeWidth: 1
    }));
    const totalHeight = titleHeight + bodyHeight;
    const totalWidth = maxWidth || 400;
    return {
      svg: elements.join("\n"),
      width: totalWidth,
      height: totalHeight
    };
  }
  function renderStrFragInvocation2(block, x, y, _maxWidth) {
    const elements = [];
    let currentX = x;
    const fontSize = FONT_SIZES.normal;
    const padding = SPACING.blockPadding;
    let fullText = `Frag ${block.name}`;
    if (block.arguments.length > 0) {
      const argsText = block.arguments.map((arg) => textArgsToText(arg)).join(", ");
      fullText += `[${argsText}]`;
    }
    const textWidth = measureText(fullText, fontSize);
    const boxWidth = textWidth + padding * 2 + 4;
    const boxHeight = fontSize + padding * 2;
    elements.push(svgRect(currentX, y, boxWidth, boxHeight, {
      fill: COLORS.funcBg,
      stroke: COLORS.func,
      strokeWidth: 1,
      rx: 3
    }));
    const textY = y + padding + fontSize * 0.85;
    let textX = currentX + padding + 2;
    elements.push(svgText(textX, textY, "Frag", {
      fill: COLORS.nameRef,
      fontSize,
      fontWeight: "600"
    }));
    textX += measureText("Frag", fontSize) + 4;
    elements.push(svgText(textX, textY, block.name, {
      fill: COLORS.func,
      fontSize,
      fontWeight: "600"
    }));
    textX += measureText(block.name, fontSize);
    if (block.arguments.length > 0) {
      elements.push(svgText(textX, textY, "[", {
        fill: COLORS.func,
        fontSize,
        fontWeight: "500"
      }));
      textX += measureText("[", fontSize);
      for (let i = 0; i < block.arguments.length; i++) {
        if (i > 0) {
          elements.push(svgText(textX, textY, ", ", {
            fill: COLORS.func,
            fontSize
          }));
          textX += measureText(", ", fontSize);
        }
        const argText = textArgsToText(block.arguments[i]);
        elements.push(svgText(textX, textY, argText, {
          fill: COLORS.func,
          fontSize
        }));
        textX += measureText(argText, fontSize);
      }
      elements.push(svgText(textX, textY, "]", {
        fill: COLORS.func,
        fontSize,
        fontWeight: "500"
      }));
    }
    return {
      svg: elements.join("\n"),
      width: boxWidth,
      height: boxHeight
    };
  }
  function renderRolesFragInvocation2(block, x, y, _maxWidth) {
    const elements = [];
    let currentX = x;
    const fontSize = FONT_SIZES.normal;
    const padding = SPACING.blockPadding;
    let fullText = `Frag ${block.name}`;
    if (block.arguments.length > 0) {
      const argsText = block.arguments.map((arg) => textArgsToText(arg)).join(", ");
      fullText += `[${argsText}]`;
    }
    const textWidth = measureText(fullText, fontSize);
    const boxWidth = textWidth + padding * 2 + 4;
    const boxHeight = fontSize + padding * 2;
    elements.push(svgRect(currentX, y, boxWidth, boxHeight, {
      fill: COLORS.funcBg,
      stroke: COLORS.func,
      strokeWidth: 1,
      rx: 3
    }));
    const textY = y + padding + fontSize * 0.85;
    let textX = currentX + padding + 2;
    elements.push(svgText(textX, textY, "Frag", {
      fill: COLORS.nameRef,
      fontSize,
      fontWeight: "600"
    }));
    textX += measureText("Frag", fontSize) + 4;
    elements.push(svgText(textX, textY, block.name, {
      fill: COLORS.func,
      fontSize,
      fontWeight: "600"
    }));
    textX += measureText(block.name, fontSize);
    if (block.arguments.length > 0) {
      elements.push(svgText(textX, textY, "[", {
        fill: COLORS.func,
        fontSize,
        fontWeight: "500"
      }));
      textX += measureText("[", fontSize);
      for (let i = 0; i < block.arguments.length; i++) {
        if (i > 0) {
          elements.push(svgText(textX, textY, ", ", {
            fill: COLORS.func,
            fontSize
          }));
          textX += measureText(", ", fontSize);
        }
        const argText = textArgsToText(block.arguments[i]);
        elements.push(svgText(textX, textY, argText, {
          fill: COLORS.func,
          fontSize
        }));
        textX += measureText(argText, fontSize);
      }
      elements.push(svgText(textX, textY, "]", {
        fill: COLORS.func,
        fontSize,
        fontWeight: "500"
      }));
    }
    return {
      svg: elements.join("\n"),
      width: boxWidth,
      height: boxHeight
    };
  }
  function renderRoleBody(body, startX, startY, maxWidth) {
    console.log("[renderRoleBody]", {
      hasMaxWidth: !!maxWidth,
      maxWidth,
      bodyLength: body.length
    });
    const elements = [];
    let currentY = startY;
    let overallMaxWidth = 0;
    const contentX = startX + SPACING.rolePadding;
    const effectiveMaxWidth = maxWidth || 800;
    console.log("[renderRoleBody] effectiveMaxWidth:", effectiveMaxWidth);
    let inlineGroup = [];
    const flushInlineGroup = () => {
      if (inlineGroup.length === 0) return;
      const flowResult = renderInlineBlocksWithWrap(
        inlineGroup,
        contentX,
        currentY,
        effectiveMaxWidth,
        (block, _x, _y, maxW) => renderRoleBuildingBlock2(block, 0, 0, maxW)
      );
      elements.push(flowResult.svg);
      overallMaxWidth = Math.max(overallMaxWidth, flowResult.width);
      currentY += flowResult.height + SPACING.elementGap;
      inlineGroup = [];
    };
    for (const block of body) {
      if (isInlineBlock(block.kind)) {
        inlineGroup.push(block);
      } else {
        flushInlineGroup();
        console.log("[renderRoleBody] rendering block:", block.kind, "with effectiveMaxWidth:", effectiveMaxWidth);
        const result = renderRoleBuildingBlock2(block, contentX, currentY, effectiveMaxWidth);
        elements.push(result.svg);
        overallMaxWidth = Math.max(overallMaxWidth, result.width);
        currentY += result.height + SPACING.elementGap;
      }
    }
    flushInlineGroup();
    return {
      svg: elements.join("\n"),
      width: overallMaxWidth + SPACING.rolePadding * 2,
      height: currentY - startY
    };
  }
  function renderRoleMessage2(msg, x, y, maxWidth) {
    const colors = getRoleColors(msg.role);
    const elements = [];
    let currentY = y;
    const contentX = x + 8;
    const rolePrefix = "ROLE:";
    const roleName = msg.role.toUpperCase();
    const roleGap = 2;
    const prefixWidth = measureText(rolePrefix, FONT_SIZES.roleHeader, true);
    const nameWidth = measureText(roleName, FONT_SIZES.roleHeader, true);
    const headerWidth = prefixWidth + roleGap + nameWidth + 8;
    const headerHeight = FONT_SIZES.roleHeader + 4;
    elements.push(svgRect(contentX, currentY, headerWidth, headerHeight, {
      fill: colors.bg,
      rx: 2
    }));
    const textY = currentY + FONT_SIZES.roleHeader + 1;
    const roleTextStyle = `font-family="'JetBrains Mono', monospace" font-size="${FONT_SIZES.roleHeader}" font-weight="900" fill="${colors.text}" stroke="${colors.text}" stroke-width="0.15"`;
    elements.push(`<text x="${contentX + 4}" y="${textY}" ${roleTextStyle}>${rolePrefix}</text>`);
    elements.push(`<text x="${contentX + 4 + prefixWidth + roleGap}" y="${textY}" ${roleTextStyle}>${roleName}</text>`);
    currentY += headerHeight + 2;
    const bodyMaxWidth = maxWidth ? maxWidth - 8 : void 0;
    const bodyResult = renderRoleBody(msg.body, contentX, currentY, bodyMaxWidth);
    elements.push(bodyResult.svg);
    const totalHeight = currentY - y + bodyResult.height;
    elements.push(svgLine(contentX, y, contentX, y + totalHeight, {
      stroke: colors.border,
      strokeWidth: 1
    }));
    return {
      svg: elements.join("\n"),
      width: Math.max(headerWidth, bodyResult.width) + 8,
      height: totalHeight
    };
  }
  function renderExpressionTokensSvg(tokens, startX, textY, fontSize, maxWidth, startY) {
    if (maxWidth) {
      const pass1Result = renderExpressionTokensPass1(tokens, fontSize);
      console.log("[PASS 1] width:", pass1Result.width, "maxWidth:", maxWidth, "exceeds:", pass1Result.width > maxWidth);
      console.log("[PASS 1] logical operators at:", pass1Result.logicalOpPositions);
      if (pass1Result.width <= maxWidth) {
        return renderExpressionTokensOneLine(tokens, startX, textY, fontSize);
      }
      const breakPoints = determineBreakPoints(pass1Result.logicalOpPositions, pass1Result.tokenWidths, maxWidth, startX);
      console.log("[PASS 2] break points:", breakPoints);
      return renderExpressionTokensWithBreaks(tokens, startX, textY, fontSize, breakPoints);
    }
    return renderExpressionTokensOneLine(tokens, startX, textY, fontSize);
  }
  function renderExpressionTokensPass1(tokens, fontSize) {
    console.log("[PASS 1] tokens:", tokens.map((t) => ({ type: t.type, value: t.value })));
    const actualRender = renderExpressionTokensOneLine(tokens, 0, 0, fontSize);
    const totalWidth = actualRender.width;
    const logicalOpPositions = [];
    const tokenWidths = [];
    for (let i = 0; i < tokens.length; i++) {
      const tok = tokens[i];
      if (tok.type === "LOGIC_OP" && (tok.value === "&&" || tok.value === "||")) {
        console.log(`[PASS 1] Found logical operator at ${i}:`, tok.value);
        logicalOpPositions.push(i);
        const chunkTokens = tokens.slice(0, i + 1);
        const chunkRender = renderExpressionTokensOneLine(chunkTokens, 0, 0, fontSize);
        tokenWidths[i] = chunkRender.width;
      } else if (tok.type === "KEYWORD" && (tok.value === "and" || tok.value === "or")) {
        console.log(`[PASS 1] Found logical keyword at ${i}:`, tok.value);
        logicalOpPositions.push(i);
        const chunkTokens = tokens.slice(0, i + 1);
        const chunkRender = renderExpressionTokensOneLine(chunkTokens, 0, 0, fontSize);
        tokenWidths[i] = chunkRender.width;
      }
    }
    return { width: totalWidth, logicalOpPositions, tokenWidths };
  }
  function determineBreakPoints(logicalOpPositions, tokenWidths, maxWidth, startX) {
    const breakPoints = [];
    let lineStartWidth = 0;
    for (let i = logicalOpPositions.length - 1; i >= 0; i--) {
      const opIndex = logicalOpPositions[i];
      const widthAtOp = tokenWidths[opIndex] - lineStartWidth;
      console.log(`[determineBreakPoints] op at ${opIndex}, width: ${widthAtOp}, maxWidth: ${maxWidth}`);
      if (widthAtOp > maxWidth) {
        continue;
      }
      breakPoints.unshift(opIndex);
      lineStartWidth = tokenWidths[opIndex];
      console.log(`[determineBreakPoints] Breaking after token ${opIndex}`);
    }
    return breakPoints;
  }
  function renderExpressionTokensOneLine(tokens, startX, textY, fontSize) {
    const elements = [];
    let currentX = startX;
    let currentTextY = textY;
    let i = 0;
    const smallSpace = measureText(" ", fontSize) * 0.65;
    while (i < tokens.length) {
      const tok = tokens[i];
      const noSpaceBeforeSymbols = [".", "(", ")", "[", "]", ",", ":"];
      if (tok.spaceBefore && !noSpaceBeforeSymbols.includes(tok.value)) {
        currentX += smallSpace;
      }
      if (tok.type === "KEYWORD" && ["env", "sys", "resp", "prompt"].includes(tok.value) && i + 1 < tokens.length && tokens[i + 1].type === "SYMBOL" && tokens[i + 1].value === ".") {
        let contextVarText = tok.value;
        i++;
        let parenDepth = 0;
        let bracketDepth = 0;
        while (i < tokens.length) {
          const t = tokens[i];
          if (t.value === "[") {
            bracketDepth++;
            contextVarText += t.value;
            i++;
            continue;
          }
          if (t.value === "]") {
            bracketDepth--;
            contextVarText += t.value;
            i++;
            if (bracketDepth === 0 && parenDepth === 0) {
              if (i < tokens.length && tokens[i].value === ".") {
                continue;
              }
              break;
            }
            continue;
          }
          if (t.value === "(") {
            parenDepth++;
            contextVarText += t.value;
            i++;
            continue;
          }
          if (t.value === ")") {
            parenDepth--;
            contextVarText += t.value;
            i++;
            if (bracketDepth === 0 && parenDepth === 0) {
              if (i < tokens.length && tokens[i].value === ".") {
                continue;
              }
              break;
            }
            continue;
          }
          if (parenDepth > 0 || bracketDepth > 0) {
            contextVarText += t.value;
            i++;
            continue;
          }
          if (t.value === ".") {
            contextVarText += t.value;
            i++;
            continue;
          }
          if (t.type === "IDENT" || t.type === "KEYWORD" || t.type === "NUMBER") {
            contextVarText += t.value;
            i++;
            continue;
          }
          if (t.value === "@") {
            contextVarText += t.value;
            i++;
            continue;
          }
          if (t.value === "$") {
            contextVarText += t.value;
            i++;
            continue;
          }
          break;
        }
        const ctxSegments = [];
        let pos = 0;
        while (pos < contextVarText.length) {
          const ch = contextVarText[pos];
          if (ch === "[" || ch === "]") {
            ctxSegments.push({ text: ch, type: "regular" });
            pos++;
            continue;
          }
          if (ch === "@" && pos + 1 < contextVarText.length && contextVarText[pos + 1] === "$") {
            ctxSegments.push({ text: "@", type: "index" });
            pos += 2;
            let varName = "";
            while (pos < contextVarText.length && /[A-Za-z0-9_]/.test(contextVarText[pos])) {
              varName += contextVarText[pos];
              pos++;
            }
            if (varName) {
              ctxSegments.push({ text: varName, type: "variable" });
            }
            continue;
          }
          if (ch === "@") {
            let indexText = "@";
            pos++;
            while (pos < contextVarText.length) {
              const c = contextVarText[pos];
              if (/[A-Za-z0-9_]/.test(c)) {
                indexText += c;
                pos++;
              } else if (c === "." && pos + 1 < contextVarText.length && /[A-Za-z0-9_@]/.test(contextVarText[pos + 1])) {
                indexText += c;
                pos++;
              } else {
                break;
              }
            }
            ctxSegments.push({ text: indexText, type: "index" });
            continue;
          }
          if (ch === "$") {
            pos++;
            let varName = "";
            while (pos < contextVarText.length && /[A-Za-z0-9_]/.test(contextVarText[pos])) {
              varName += contextVarText[pos];
              pos++;
            }
            if (varName) {
              ctxSegments.push({ text: varName, type: "variable" });
            }
            continue;
          }
          let regularText = "";
          while (pos < contextVarText.length && !/[@\[\]$]/.test(contextVarText[pos])) {
            regularText += contextVarText[pos];
            pos++;
          }
          if (regularText) {
            ctxSegments.push({ text: regularText, type: "regular" });
          }
        }
        let ctxTotalWidth = 0;
        for (const seg of ctxSegments) {
          const isBold = seg.type === "index";
          ctxTotalWidth += measureText(seg.text, fontSize, isBold);
        }
        const ctxPadding = 2;
        const ctxBoxWidth = ctxTotalWidth + ctxPadding * 2;
        const ctxBoxHeight = fontSize + ctxPadding * 2;
        const ctxBoxY = currentTextY - fontSize - ctxPadding + 1;
        elements.push(svgRect(currentX, ctxBoxY, ctxBoxWidth, ctxBoxHeight, {
          fill: COLORS.contextBg,
          stroke: COLORS.context,
          strokeWidth: 1,
          rx: 3
        }));
        let segX = currentX + ctxPadding;
        for (const seg of ctxSegments) {
          const displayText = seg.text;
          const isBold = seg.type === "index";
          let fill = COLORS.context;
          if (seg.type === "index") fill = COLORS.variable;
          if (seg.type === "variable") fill = COLORS.nameRef;
          elements.push(svgText(segX, currentTextY, displayText, {
            fill,
            fontSize,
            fontWeight: "600"
          }));
          segX += measureText(displayText, fontSize, isBold);
        }
        currentX += ctxBoxWidth;
        continue;
      }
      if (tok.type === "IDENT" && tok.value === "range" && i + 1 < tokens.length && tokens[i + 1].value === "(") {
        i++;
        i++;
        const startTokens = [];
        let depth = 0;
        while (i < tokens.length && !(tokens[i].value === "," && depth === 0)) {
          const t = tokens[i];
          if (t.value === "(") depth++;
          if (t.value === ")") depth--;
          startTokens.push(t);
          i++;
        }
        i++;
        const endTokens = [];
        depth = 0;
        while (i < tokens.length && !((tokens[i].value === "," || tokens[i].value === ")") && depth === 0)) {
          const t = tokens[i];
          if (t.value === "(") depth++;
          if (t.value === ")") depth--;
          endTokens.push(t);
          i++;
        }
        let stepTokens;
        if (i < tokens.length && tokens[i].value === ",") {
          i++;
          stepTokens = [];
          depth = 0;
          while (i < tokens.length && !(tokens[i].value === ")" && depth === 0)) {
            const t = tokens[i];
            if (t.value === "(") depth++;
            if (t.value === ")") depth--;
            stepTokens.push(t);
            i++;
          }
        }
        i++;
        const startResult = renderExpressionTokensSvg(startTokens, currentX, currentTextY, fontSize);
        elements.push(...startResult.elements);
        currentX += startResult.width;
        elements.push(svgText(currentX, currentTextY, "...", {
          fill: COLORS.textPrimary,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText("...", fontSize, true);
        const endResult = renderExpressionTokensSvg(endTokens, currentX, currentTextY, fontSize);
        elements.push(...endResult.elements);
        currentX += endResult.width;
        if (stepTokens) {
          const everySpace = measureText(" ", fontSize) * 0.5;
          currentX += everySpace;
          elements.push(svgText(currentX, currentTextY, "every", {
            fill: COLORS.textPrimary,
            fontSize,
            fontWeight: "700"
          }));
          currentX += measureText("every", fontSize, true);
          currentX += everySpace;
          const stepResult = renderExpressionTokensSvg(stepTokens, currentX, currentTextY, fontSize);
          elements.push(...stepResult.elements);
          currentX += stepResult.width;
        }
        continue;
      }
      if (tok.type === "IDENT" && i + 1 < tokens.length && tokens[i + 1].value === "(") {
        const funcName = tok.value;
        i++;
        i++;
        const argTokens = [];
        let depth = 1;
        while (i < tokens.length && depth > 0) {
          const t = tokens[i];
          if (t.value === "(") depth++;
          if (t.value === ")") depth--;
          if (depth > 0) {
            argTokens.push(t);
          }
          i++;
        }
        const isBuiltinMath = funcName === "min" || funcName === "max";
        const funcColor = isBuiltinMath ? COLORS.textPrimary : COLORS.func;
        elements.push(svgText(currentX, currentTextY, funcName, {
          fill: funcColor,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(funcName, fontSize, true);
        elements.push(svgText(currentX, currentTextY, "(", {
          fill: funcColor,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText("(", fontSize, true);
        const argsResult = renderExpressionTokensSvg(argTokens, currentX, currentTextY, fontSize);
        elements.push(...argsResult.elements);
        currentX += argsResult.width;
        elements.push(svgText(currentX, currentTextY, ")", {
          fill: funcColor,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(")", fontSize, true);
        continue;
      }
      if (tok.type === "SYMBOL" && tok.value === "@" && i + 1 < tokens.length) {
        const nextTok = tokens[i + 1];
        if (nextTok.type === "SYMBOL" && nextTok.value === "$" && i + 2 < tokens.length) {
          const varNameTok = tokens[i + 2];
          if (varNameTok.type === "IDENT") {
            elements.push(svgText(currentX, currentTextY, "@", {
              fill: COLORS.variable,
              fontSize,
              fontWeight: "700"
            }));
            currentX += measureText("@", fontSize, true);
            elements.push(svgText(currentX, currentTextY, varNameTok.value, {
              fill: COLORS.nameRef,
              fontSize,
              fontWeight: "700"
            }));
            currentX += measureText(varNameTok.value, fontSize, true);
            i += 3;
            continue;
          }
        }
        if (nextTok.type === "IDENT" || nextTok.type === "NUMBER") {
          let timeIndexText = "@" + nextTok.value;
          i += 2;
          while (i < tokens.length && tokens[i].value === "." && i + 1 < tokens.length && (tokens[i + 1].type === "IDENT" || tokens[i + 1].type === "NUMBER" || tokens[i + 1].value === "@")) {
            timeIndexText += ".";
            i++;
            if (tokens[i].value === "@") {
              timeIndexText += "@";
              i++;
            }
            if (i < tokens.length && (tokens[i].type === "IDENT" || tokens[i].type === "NUMBER")) {
              timeIndexText += tokens[i].value;
              i++;
            }
          }
          elements.push(svgText(currentX, currentTextY, timeIndexText, {
            fill: COLORS.variable,
            fontSize,
            fontWeight: "700"
          }));
          currentX += measureText(timeIndexText, fontSize, true);
          continue;
        }
      }
      if (tok.type === "SYMBOL" && tok.value === "$" && i + 1 < tokens.length) {
        const nextTok = tokens[i + 1];
        if (nextTok.type === "IDENT") {
          let nameRefText = nextTok.value;
          i += 2;
          while (i < tokens.length) {
            if (tokens[i].value === "." && i + 1 < tokens.length && tokens[i + 1].type === "IDENT") {
              nameRefText += "." + tokens[i + 1].value;
              i += 2;
            } else if (tokens[i].value === "[") {
              let bracketDepth = 1;
              nameRefText += "[";
              i++;
              while (i < tokens.length && bracketDepth > 0) {
                if (tokens[i].value === "[") bracketDepth++;
                if (tokens[i].value === "]") bracketDepth--;
                nameRefText += tokens[i].value;
                i++;
              }
            } else {
              break;
            }
          }
          elements.push(svgText(currentX, currentTextY, nameRefText, {
            fill: COLORS.nameRef,
            fontSize,
            fontWeight: "700"
          }));
          currentX += measureText(nameRefText, fontSize, true);
          continue;
        }
      }
      if (tok.type === "LOGIC_OP") {
        let combined = tok.value;
        i++;
        while (i < tokens.length && tokens[i].type === "LOGIC_OP") {
          combined += tokens[i].value;
          i++;
        }
        if (!tok.spaceBefore && currentX > startX) {
          currentX += smallSpace;
        }
        elements.push(svgText(currentX, currentTextY, combined, {
          fill: COLORS.textPrimary,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(combined, fontSize, false);
        currentX += smallSpace;
        continue;
      }
      if (tok.type === "ARITH_OP") {
        const needsSpacing = tok.value === "%";
        if (needsSpacing && !tok.spaceBefore && currentX > startX) {
          currentX += smallSpace;
        }
        elements.push(svgText(currentX, currentTextY, tok.value, {
          fill: COLORS.textPrimary,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(tok.value, fontSize, false);
        if (needsSpacing) {
          currentX += smallSpace;
        }
        i++;
        continue;
      }
      if (tok.type === "RANGE") {
        elements.push(svgText(currentX, currentTextY, tok.value, {
          fill: COLORS.textPrimary,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(tok.value, fontSize, false);
        i++;
        continue;
      }
      if (tok.type === "STRING") {
        elements.push(svgText(currentX, currentTextY, tok.value, {
          fill: COLORS.string,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(tok.value, fontSize, false);
        i++;
        continue;
      }
      if (tok.type === "NUMBER") {
        elements.push(svgText(currentX, currentTextY, tok.value, {
          fill: COLORS.variable,
          fontSize,
          fontWeight: "700"
        }));
        currentX += measureText(tok.value, fontSize, true);
        i++;
        continue;
      }
      if (tok.type === "KEYWORD") {
        const needsSpacing = ["and", "or", "not", "for", "in", "when", "every"].includes(tok.value);
        if (needsSpacing && currentX > startX && !tok.spaceBefore) {
          currentX += smallSpace;
        }
        elements.push(svgText(currentX, currentTextY, tok.value, {
          fill: COLORS.textPrimary,
          fontSize,
          fontWeight: "700"
        }));
        currentX += measureText(tok.value, fontSize, true);
        if (needsSpacing) {
          currentX += smallSpace;
        }
        i++;
        continue;
      }
      if (tok.type === "IDENT") {
        elements.push(svgText(currentX, currentTextY, tok.value, {
          fill: COLORS.textPrimary,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(tok.value, fontSize, false);
        i++;
        continue;
      }
      if (tok.type === "SYMBOL") {
        if (tok.value === ",") {
          elements.push(svgText(currentX, currentTextY, tok.value, {
            fill: COLORS.textPrimary,
            fontSize,
            fontWeight: "600"
          }));
          currentX += measureText(tok.value, fontSize, false);
          currentX += measureText(" ", fontSize) * 0.5;
          i++;
          continue;
        }
        elements.push(svgText(currentX, currentTextY, tok.value, {
          fill: COLORS.textPrimary,
          fontSize,
          fontWeight: "600"
        }));
        currentX += measureText(tok.value, fontSize, false);
        i++;
        continue;
      }
      elements.push(svgText(currentX, currentTextY, tok.value, {
        fill: COLORS.textPrimary,
        fontSize,
        fontWeight: "600"
      }));
      currentX += measureText(tok.value, fontSize, false);
      i++;
    }
    return {
      elements,
      width: currentX - startX,
      height: void 0,
      lastLineY: void 0
    };
  }
  function renderExpressionTokensWithBreaks(tokens, startX, textY, fontSize, breakPoints) {
    const elements = [];
    let currentTextY = textY;
    let maxRenderedWidth = 0;
    const lineHeight = getLineHeight(fontSize);
    console.log("[renderWithBreaks] Starting render with", breakPoints.length, "break points:", breakPoints);
    let lineStartIdx = 0;
    for (let i = 0; i <= breakPoints.length; i++) {
      const lineEndIdx = i < breakPoints.length ? breakPoints[i] + 1 : tokens.length;
      const lineTokens = tokens.slice(lineStartIdx, lineEndIdx);
      if (lineTokens.length > 0) {
        console.log(`[renderWithBreaks] Rendering line ${i}: tokens ${lineStartIdx} to ${lineEndIdx - 1}`);
        const lineResult = renderExpressionTokensOneLine(lineTokens, startX, currentTextY, fontSize);
        elements.push(...lineResult.elements);
        maxRenderedWidth = Math.max(maxRenderedWidth, lineResult.width);
        if (i < breakPoints.length) {
          currentTextY += lineHeight;
        }
      }
      lineStartIdx = lineEndIdx;
    }
    const totalHeight = currentTextY - textY + fontSize;
    return {
      elements,
      width: maxRenderedWidth,
      height: breakPoints.length > 0 ? totalHeight : void 0,
      lastLineY: breakPoints.length > 0 ? currentTextY : void 0
    };
  }
  function renderControlFlowHeader(keyword, symbol, tokens, suffix, x, y, maxWidth) {
    const elements = [];
    const keywordFontSize = FONT_SIZES.header + 2;
    const symbolFontSize = 11;
    let currentX = x + 5;
    let currentY = y;
    const textY = y + keywordFontSize + 1;
    let maxRenderedWidth = 0;
    if (symbol) {
      elements.push(svgText(currentX, textY, symbol, {
        fill: COLORS.controlBorder,
        fontSize: symbolFontSize,
        fontWeight: "600"
      }));
      currentX += 13;
    }
    elements.push(svgText(currentX, textY, keyword, {
      fill: COLORS.textPrimary,
      fontSize: keywordFontSize,
      fontWeight: "900"
    }));
    currentX += measureText(keyword, keywordFontSize, true) + 4;
    maxRenderedWidth = Math.max(maxRenderedWidth, currentX - x);
    const tokensMaxWidth = maxWidth ? maxWidth - (currentX - x) - 8 : void 0;
    if (maxWidth) {
      console.log("[renderControlFlowHeader]", {
        keyword,
        maxWidth,
        usedWidth: currentX - x,
        tokensMaxWidth,
        tokens: tokens.map((t) => t.value).join("")
      });
    }
    const tokenResult = renderExpressionTokensSvg(
      tokens,
      currentX,
      textY,
      keywordFontSize,
      tokensMaxWidth,
      maxWidth ? y : void 0
    );
    elements.push(...tokenResult.elements);
    if (tokenResult.height !== void 0) {
      currentY += tokenResult.height;
      maxRenderedWidth = Math.max(maxRenderedWidth, tokenResult.width);
      currentX = x + tokenResult.width;
    } else {
      currentX += tokenResult.width;
      maxRenderedWidth = Math.max(maxRenderedWidth, currentX - x);
    }
    if (suffix) {
      const suffixY = tokenResult.lastLineY !== void 0 ? tokenResult.lastLineY : textY;
      elements.push(svgText(currentX, suffixY, suffix, {
        fill: COLORS.textPrimary,
        fontSize: keywordFontSize,
        fontWeight: "600"
      }));
      const suffixWidth = measureText(suffix, keywordFontSize, true);
      currentX += suffixWidth;
      maxRenderedWidth = Math.max(maxRenderedWidth, currentX - x);
    }
    const headerHeight = tokenResult.height !== void 0 ? tokenResult.height + keywordFontSize + 6 : keywordFontSize + 6;
    const boxWidth = maxRenderedWidth + 8;
    const bgRect = svgRect(x, y, boxWidth, headerHeight, {
      fill: COLORS.controlHeaderBg,
      rx: 2
    });
    return {
      svg: bgRect + "\n" + elements.join("\n"),
      width: boxWidth,
      height: headerHeight
    };
  }
  function iterableToTokens(iterable) {
    if (iterable.kind === "range-expr") {
      const tokens = [];
      tokens.push(...iterable.start);
      tokens.push({ type: "RANGE", value: "..." });
      tokens.push(...iterable.end);
      if (iterable.step) {
        tokens.push({ type: "KEYWORD", value: "every", spaceBefore: true });
        tokens.push(...iterable.step);
      }
      return tokens;
    }
    return iterable.tokens;
  }
  function renderLoopHeader(indexValue, iterable, x, y) {
    const elements = [];
    const keywordFontSize = FONT_SIZES.header + 2;
    const symbolFontSize = 11;
    const fontSize = keywordFontSize;
    const headerHeight = keywordFontSize + 6;
    let currentX = x + 5;
    const textY = y + keywordFontSize + 1;
    elements.push(svgText(currentX, textY, "\u21BB", {
      fill: COLORS.controlBorder,
      fontSize: symbolFontSize,
      fontWeight: "600"
    }));
    currentX += 13;
    elements.push(svgText(currentX, textY, "ForEach", {
      fill: COLORS.textPrimary,
      fontSize: keywordFontSize,
      fontWeight: "900"
    }));
    currentX += measureText("ForEach", keywordFontSize, true) + 4;
    const indexText = indexValueToText(indexValue);
    elements.push(svgText(currentX, textY, indexText, {
      fill: COLORS.variable,
      fontSize,
      fontWeight: "700"
    }));
    currentX += measureText(indexText, fontSize, true) + 3;
    elements.push(svgText(currentX, textY, ": ", {
      fill: COLORS.textPrimary,
      fontSize,
      fontWeight: "600"
    }));
    currentX += measureText(": ", fontSize, true);
    const iterTokens = iterableToTokens(iterable);
    const tokenResult = renderExpressionTokensSvg(iterTokens, currentX, textY, fontSize);
    elements.push(...tokenResult.elements);
    currentX += tokenResult.width;
    const bgRect = svgRect(x, y, currentX - x + 8, headerHeight, {
      fill: COLORS.controlHeaderBg,
      rx: 2
    });
    return {
      svg: bgRect + "\n" + elements.join("\n"),
      width: currentX - x + 8,
      height: headerHeight
    };
  }
  function renderLoopOutsideRole2(block, x, y, maxWidth) {
    const elements = [];
    let currentY = y;
    const headerResult = renderLoopHeader(block.index.value, block.iterable, x + 8, currentY);
    elements.push(headerResult.svg);
    currentY += headerResult.height + 5;
    const childMaxWidth = maxWidth ? maxWidth - SPACING.indentSize - 8 : void 0;
    let resultMaxWidth = headerResult.width;
    for (const child of block.body) {
      const childResult = renderTopLevelBlock2(child, x + SPACING.indentSize + 8, currentY, childMaxWidth);
      elements.push(childResult.svg);
      resultMaxWidth = Math.max(resultMaxWidth, childResult.width + SPACING.indentSize);
      currentY += childResult.height + SPACING.blockGap;
    }
    const totalHeight = currentY - y;
    elements.push(svgLine(x + 8, y, x + 8, y + totalHeight, {
      stroke: COLORS.controlBorder,
      strokeWidth: 1
    }));
    return {
      svg: elements.join("\n"),
      width: resultMaxWidth + 8,
      height: totalHeight
    };
  }
  function renderLoopInsideRole2(block, x, y, maxWidthParam) {
    const elements = [];
    let currentY = y;
    console.log("[renderLoopInsideRole]", {
      hasMaxWidthParam: !!maxWidthParam,
      maxWidthParam,
      bodyLength: block.body.length
    });
    const headerResult = renderLoopHeader(block.index.value, block.iterable, x + 8, currentY);
    elements.push(headerResult.svg);
    currentY += headerResult.height + 5;
    const childMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize - 8 : void 0;
    console.log("[renderLoopInsideRole] childMaxWidth:", childMaxWidth);
    let maxWidth = headerResult.width;
    for (const child of block.body) {
      console.log("[renderLoopInsideRole] rendering child:", child.kind);
      const childResult = renderRoleBuildingBlock2(child, x + SPACING.indentSize + 8, currentY, childMaxWidth);
      elements.push(childResult.svg);
      maxWidth = Math.max(maxWidth, childResult.width + SPACING.indentSize);
      currentY += childResult.height + SPACING.elementGap;
    }
    const totalHeight = currentY - y;
    elements.push(svgLine(x + 8, y, x + 8, y + totalHeight, {
      stroke: COLORS.controlBorder,
      strokeWidth: 1
    }));
    return {
      svg: elements.join("\n"),
      width: maxWidth + 8,
      height: totalHeight
    };
  }
  function renderConditionalOutsideRole2(block, x, y, maxWidthParam) {
    const elements = [];
    let currentY = y;
    let resultMaxWidth = 0;
    const childMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize - 8 : void 0;
    const ifHeader = renderControlFlowHeader("If", "\u25C7", block.Ifcondition, ":", x + 8, currentY, maxWidthParam);
    elements.push(ifHeader.svg);
    resultMaxWidth = Math.max(resultMaxWidth, ifHeader.width);
    currentY += ifHeader.height + 5;
    for (const child of block.IfBody) {
      const childResult = renderTopLevelBlock2(child, x + SPACING.indentSize + 8, currentY, childMaxWidth);
      elements.push(childResult.svg);
      resultMaxWidth = Math.max(resultMaxWidth, childResult.width + SPACING.indentSize);
      currentY += childResult.height + SPACING.blockGap;
    }
    for (let i = 0; i < block.elseif.length; i++) {
      const elseifHeader = renderControlFlowHeader("ElseIf", "\u25C7", block.elseif[i], ":", x + 8, currentY, maxWidthParam);
      elements.push(elseifHeader.svg);
      resultMaxWidth = Math.max(resultMaxWidth, elseifHeader.width);
      currentY += elseifHeader.height + 5;
      for (const child of block.elseifBody[i]) {
        const childResult = renderTopLevelBlock2(child, x + SPACING.indentSize + 8, currentY, childMaxWidth);
        elements.push(childResult.svg);
        resultMaxWidth = Math.max(resultMaxWidth, childResult.width + SPACING.indentSize);
        currentY += childResult.height + SPACING.blockGap;
      }
    }
    if (block.elseBody && block.elseBody.length > 0) {
      const elseHeader = renderControlFlowHeader("Else", "\u25C7", [], ":", x + 8, currentY, maxWidthParam);
      elements.push(elseHeader.svg);
      resultMaxWidth = Math.max(resultMaxWidth, elseHeader.width);
      currentY += elseHeader.height + 5;
      for (const child of block.elseBody) {
        const childResult = renderTopLevelBlock2(child, x + SPACING.indentSize + 8, currentY, childMaxWidth);
        elements.push(childResult.svg);
        resultMaxWidth = Math.max(resultMaxWidth, childResult.width + SPACING.indentSize);
        currentY += childResult.height + SPACING.blockGap;
      }
    }
    const totalHeight = currentY - y;
    elements.push(svgLine(x + 8, y, x + 8, y + totalHeight, {
      stroke: COLORS.controlBorder,
      strokeWidth: 1
    }));
    return {
      svg: elements.join("\n"),
      width: resultMaxWidth + 8,
      height: totalHeight
    };
  }
  function renderConditionalInsideRole2(block, x, y, maxWidthParam) {
    const elements = [];
    let currentY = y;
    let maxWidth = 0;
    console.log("[renderConditionalInsideRole]", {
      hasMaxWidthParam: !!maxWidthParam,
      maxWidthParam,
      condition: block.Ifcondition.map((t) => t.value).join("")
    });
    const ifHeader = renderControlFlowHeader("If", "\u25C7", block.Ifcondition, ":", x + 8, currentY, maxWidthParam);
    elements.push(ifHeader.svg);
    maxWidth = Math.max(maxWidth, ifHeader.width);
    currentY += ifHeader.height + 5;
    const childMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize - 8 : void 0;
    console.log("[renderConditionalInsideRole] childMaxWidth for IfBody:", childMaxWidth, "from maxWidthParam:", maxWidthParam);
    for (const child of block.IfBody) {
      console.log("[renderConditionalInsideRole] rendering IfBody child:", child.kind, "with childMaxWidth:", childMaxWidth);
      const childResult = renderRoleBuildingBlock2(child, x + SPACING.indentSize + 8, currentY, childMaxWidth);
      elements.push(childResult.svg);
      maxWidth = Math.max(maxWidth, childResult.width + SPACING.indentSize);
      currentY += childResult.height + SPACING.elementGap;
    }
    for (let i = 0; i < block.elseif.length; i++) {
      const elseifHeader = renderControlFlowHeader("ElseIf", "\u25C7", block.elseif[i], ":", x + 8, currentY, maxWidthParam);
      elements.push(elseifHeader.svg);
      maxWidth = Math.max(maxWidth, elseifHeader.width);
      currentY += elseifHeader.height + 5;
      for (const child of block.elseifBody[i]) {
        const childResult = renderRoleBuildingBlock2(child, x + SPACING.indentSize + 8, currentY, childMaxWidth);
        elements.push(childResult.svg);
        maxWidth = Math.max(maxWidth, childResult.width + SPACING.indentSize);
        currentY += childResult.height + SPACING.elementGap;
      }
    }
    if (block.elseBody && block.elseBody.length > 0) {
      const elseHeader = renderControlFlowHeader("Else", "\u25C7", [], ":", x + 8, currentY, maxWidthParam);
      elements.push(elseHeader.svg);
      maxWidth = Math.max(maxWidth, elseHeader.width);
      currentY += elseHeader.height + 5;
      for (const child of block.elseBody) {
        const childResult = renderRoleBuildingBlock2(child, x + SPACING.indentSize + 8, currentY, childMaxWidth);
        elements.push(childResult.svg);
        maxWidth = Math.max(maxWidth, childResult.width + SPACING.indentSize);
        currentY += childResult.height + SPACING.elementGap;
      }
    }
    const totalHeight = currentY - y;
    elements.push(svgLine(x + 8, y, x + 8, y + totalHeight, {
      stroke: COLORS.controlBorder,
      strokeWidth: 1
    }));
    return {
      svg: elements.join("\n"),
      width: maxWidth + 8,
      height: totalHeight
    };
  }
  function renderSwitchOutsideRole2(block, x, y, maxWidthParam) {
    const elements = [];
    let currentY = y;
    let resultMaxWidth = 0;
    const childMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize * 2 - 8 : void 0;
    const switchTokens = [
      { type: "SYMBOL", value: "(" },
      ...block.expression,
      { type: "SYMBOL", value: ")" }
    ];
    const switchHeader = renderControlFlowHeader("Switch", "\u2387", switchTokens, ":", x + 8, currentY, maxWidthParam);
    elements.push(switchHeader.svg);
    resultMaxWidth = Math.max(resultMaxWidth, switchHeader.width);
    currentY += switchHeader.height + 4;
    for (const c of block.cases) {
      const caseMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize : void 0;
      const caseHeader = renderControlFlowHeader("Case", "", c.match, "", x + SPACING.indentSize + 8, currentY, caseMaxWidth);
      elements.push(caseHeader.svg);
      resultMaxWidth = Math.max(resultMaxWidth, caseHeader.width + SPACING.indentSize);
      currentY += caseHeader.height + 5;
      for (const child of c.body) {
        const childResult = renderTopLevelBlock2(child, x + SPACING.indentSize * 2 + 8, currentY, childMaxWidth);
        elements.push(childResult.svg);
        resultMaxWidth = Math.max(resultMaxWidth, childResult.width + SPACING.indentSize * 2);
        currentY += childResult.height + SPACING.blockGap;
      }
    }
    if (block.defaultCase) {
      const caseMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize : void 0;
      const defaultHeader = renderControlFlowHeader("Default", "", [], ":", x + SPACING.indentSize + 8, currentY, caseMaxWidth);
      elements.push(defaultHeader.svg);
      resultMaxWidth = Math.max(resultMaxWidth, defaultHeader.width + SPACING.indentSize);
      currentY += defaultHeader.height + 5;
      for (const child of block.defaultCase.body) {
        const childResult = renderTopLevelBlock2(child, x + SPACING.indentSize * 2 + 8, currentY, childMaxWidth);
        elements.push(childResult.svg);
        resultMaxWidth = Math.max(resultMaxWidth, childResult.width + SPACING.indentSize * 2);
        currentY += childResult.height + SPACING.blockGap;
      }
    }
    const totalHeight = currentY - y;
    elements.push(svgLine(x + 8, y, x + 8, y + totalHeight, {
      stroke: COLORS.controlBorder,
      strokeWidth: 1
    }));
    return {
      svg: elements.join("\n"),
      width: resultMaxWidth + 8,
      height: totalHeight
    };
  }
  function renderSwitchInsideRole2(block, x, y, maxWidthParam) {
    const elements = [];
    let currentY = y;
    let maxWidth = 0;
    const switchTokens = [
      { type: "SYMBOL", value: "(" },
      ...block.expression,
      { type: "SYMBOL", value: ")" }
    ];
    const switchHeader = renderControlFlowHeader("Switch", "\u2387", switchTokens, ":", x + 8, currentY, maxWidthParam);
    elements.push(switchHeader.svg);
    maxWidth = Math.max(maxWidth, switchHeader.width);
    currentY += switchHeader.height + 4;
    for (const c of block.cases) {
      const caseMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize : void 0;
      const caseHeader = renderControlFlowHeader("Case", "", c.match, "", x + SPACING.indentSize + 8, currentY, caseMaxWidth);
      elements.push(caseHeader.svg);
      maxWidth = Math.max(maxWidth, caseHeader.width + SPACING.indentSize);
      currentY += caseHeader.height + 5;
      const caseBodyMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize * 2 - 8 : void 0;
      for (const child of c.body) {
        const childResult = renderRoleBuildingBlock2(child, x + SPACING.indentSize * 2 + 8, currentY, caseBodyMaxWidth);
        elements.push(childResult.svg);
        maxWidth = Math.max(maxWidth, childResult.width + SPACING.indentSize * 2);
        currentY += childResult.height + SPACING.elementGap;
      }
    }
    if (block.defaultCase) {
      const caseMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize : void 0;
      const defaultHeader = renderControlFlowHeader("Default", "", [], ":", x + SPACING.indentSize + 8, currentY, caseMaxWidth);
      elements.push(defaultHeader.svg);
      maxWidth = Math.max(maxWidth, defaultHeader.width + SPACING.indentSize);
      currentY += defaultHeader.height + 5;
      const defaultBodyMaxWidth = maxWidthParam ? maxWidthParam - SPACING.indentSize * 2 - 8 : void 0;
      for (const child of block.defaultCase.body) {
        const childResult = renderRoleBuildingBlock2(child, x + SPACING.indentSize * 2 + 8, currentY, defaultBodyMaxWidth);
        elements.push(childResult.svg);
        maxWidth = Math.max(maxWidth, childResult.width + SPACING.indentSize * 2);
        currentY += childResult.height + SPACING.elementGap;
      }
    }
    const totalHeight = currentY - y;
    elements.push(svgLine(x + 8, y, x + 8, y + totalHeight, {
      stroke: COLORS.controlBorder,
      strokeWidth: 1
    }));
    return {
      svg: elements.join("\n"),
      width: maxWidth + 8,
      height: totalHeight
    };
  }
  function renderMarkBlock2(block, x, y, maxWidthParam) {
    const elements = [];
    let currentY = y;
    let resultMaxWidth = 0;
    const childMaxWidth = maxWidthParam ? maxWidthParam - 25 : void 0;
    for (const child of block.body) {
      const childResult = renderTopLevelBlock2(child, x, currentY, childMaxWidth);
      elements.push(childResult.svg);
      resultMaxWidth = Math.max(resultMaxWidth, childResult.width);
      currentY += childResult.height + SPACING.blockGap;
    }
    const totalHeight = currentY - y;
    const bracketX = x + resultMaxWidth + 8;
    const markNum = block.markNumber !== void 0 && !isNaN(block.markNumber) ? block.markNumber : 0;
    elements.push(svgLine(bracketX, y, bracketX + 5, y, { stroke: "#000000", strokeWidth: 2 }));
    elements.push(svgLine(bracketX + 5, y, bracketX + 5, y + totalHeight, { stroke: "#000000", strokeWidth: 2 }));
    elements.push(svgLine(bracketX, y + totalHeight, bracketX + 5, y + totalHeight, { stroke: "#000000", strokeWidth: 2 }));
    elements.push(svgText(bracketX + 10, y + totalHeight / 2 + FONT_SIZES.normal / 3, String(markNum), {
      fill: "#000000",
      fontSize: FONT_SIZES.normal,
      fontWeight: "700"
    }));
    return {
      svg: elements.join("\n"),
      width: resultMaxWidth + 25,
      height: totalHeight
    };
  }
  function renderMarkBlockInsideRole2(block, x, y, maxWidthParam) {
    const elements = [];
    let currentY = y;
    let maxWidth = 0;
    const childMaxWidth = maxWidthParam ? maxWidthParam - 25 : void 0;
    for (const child of block.body) {
      const childResult = renderRoleBuildingBlock2(child, x, currentY, childMaxWidth);
      elements.push(childResult.svg);
      maxWidth = Math.max(maxWidth, childResult.width);
      currentY += childResult.height + SPACING.elementGap;
    }
    const totalHeight = currentY - y;
    const bracketX = x + maxWidth + 8;
    const markNum = block.markNumber !== void 0 && !isNaN(block.markNumber) ? block.markNumber : 0;
    elements.push(svgLine(bracketX, y, bracketX + 5, y, { stroke: "#000000", strokeWidth: 2 }));
    elements.push(svgLine(bracketX + 5, y, bracketX + 5, y + totalHeight, { stroke: "#000000", strokeWidth: 2 }));
    elements.push(svgLine(bracketX, y + totalHeight, bracketX + 5, y + totalHeight, { stroke: "#000000", strokeWidth: 2 }));
    elements.push(svgText(bracketX + 10, y + totalHeight / 2 + FONT_SIZES.normal / 3, String(markNum), {
      fill: "#000000",
      fontSize: FONT_SIZES.normal,
      fontWeight: "700"
    }));
    return {
      svg: elements.join("\n"),
      width: maxWidth + 25,
      height: totalHeight
    };
  }
  function renderNoneMessage2(msg, x, y) {
    const colors = getRoleColors("none");
    const elements = [];
    let currentY = y;
    const headerText = "Completion Prompt (no role)";
    const headerWidth = measureText(headerText.toUpperCase(), FONT_SIZES.roleHeader, true) + 8;
    const headerHeight = FONT_SIZES.roleHeader + 4;
    elements.push(svgRect(x, currentY, headerWidth, headerHeight, {
      fill: colors.bg,
      rx: 2
    }));
    elements.push(svgText(x + 4, currentY + FONT_SIZES.roleHeader + 1, headerText.toUpperCase(), {
      fill: colors.text,
      fontSize: FONT_SIZES.roleHeader,
      fontWeight: "900"
    }));
    currentY += headerHeight + 2;
    const bodyResult = renderRoleBody(msg.body, x, currentY);
    elements.push(bodyResult.svg);
    const totalHeight = currentY - y + bodyResult.height;
    elements.push(svgLine(x, y, x, y + totalHeight, {
      stroke: colors.border,
      strokeWidth: 1
    }));
    return {
      svg: elements.join("\n"),
      width: Math.max(headerWidth, bodyResult.width),
      height: totalHeight
    };
  }
  function renderTopLevelBlock2(block, x, y, maxWidth) {
    switch (block.kind) {
      case "role-message":
        return renderRoleMessage2(block, x, y, maxWidth);
      case "conditional-block-outside-role":
        return renderConditionalOutsideRole2(block, x, y, maxWidth);
      case "loop-block-outside-role":
        return renderLoopOutsideRole2(block, x, y, maxWidth);
      case "switch-block-outside-role":
        return renderSwitchOutsideRole2(block, x, y, maxWidth);
      case "comment-block":
        return renderComment(block.text, x, y, true, maxWidth);
      case "mark-block":
        return renderMarkBlock2(block, x, y, maxWidth);
      case "name-def":
        return renderNameDef2(block, x, y, maxWidth);
      case "end-block":
        return renderEndBlock2(block, x, y);
      case "roles-frag-invocation":
        return renderRolesFragInvocation2(block, x, y, maxWidth);
      default:
        return { svg: "", width: 0, height: 0 };
    }
  }
  function renderPromptBody2(body, x, y, maxWidthParam) {
    if (body.kind === "chat-prompt-body") {
      const elements = [];
      let currentY = y;
      let resultMaxWidth = 0;
      for (const item of body.body) {
        const result = renderTopLevelBlock2(item, x, currentY, maxWidthParam);
        elements.push(result.svg);
        resultMaxWidth = Math.max(resultMaxWidth, result.width);
        currentY += result.height + SPACING.blockGap;
      }
      return {
        svg: elements.join("\n"),
        width: resultMaxWidth,
        height: currentY - y
      };
    } else {
      return renderNoneMessage2(body.message, x, y);
    }
  }
  function renderPromptTitle2(title, x, y, containerWidth) {
    const elements = [];
    let indexText = "";
    if (title.indices.length > 0) {
      indexText = "[" + title.indices.map(indexToText).join(",") + "]";
    }
    const fullTitle = title.name + indexText;
    const titleWidth = measureText(fullTitle, FONT_SIZES.title, true);
    const boxWidth = Math.max(titleWidth + 16, containerWidth);
    const boxHeight = FONT_SIZES.title + 6;
    elements.push(svgRect(x, y, boxWidth, boxHeight, {
      fill: COLORS.bgSecondary,
      stroke: COLORS.borderMedium,
      strokeWidth: 1,
      rx: 3
    }));
    let textX = x + 8;
    const textY = y + FONT_SIZES.title + 2;
    elements.push(svgText(textX, textY, title.name, {
      fill: COLORS.textPrimary,
      fontSize: FONT_SIZES.title,
      fontWeight: "700"
    }));
    textX += measureText(title.name, FONT_SIZES.title, true);
    if (indexText) {
      elements.push(svgText(textX, textY, indexText, {
        fill: COLORS.variable,
        fontSize: FONT_SIZES.title,
        fontWeight: "700"
      }));
    }
    return {
      svg: elements.join("\n"),
      width: boxWidth,
      height: boxHeight
    };
  }
  function renderPromptsSvg(blocks, maxWidth) {
    loadFonts();
    const startX = SPACING.containerPaddingLeft;
    let maxContentWidth = 0;
    for (const block of blocks) {
      if (block.kind === "prompt") {
        const bodyResult = renderPromptBody2(block.body, startX, 0);
        maxContentWidth = Math.max(maxContentWidth, bodyResult.width + startX);
      } else if (block.kind === "comment-block") {
        const commentResult = renderComment(block.text, startX, 0);
        maxContentWidth = Math.max(maxContentWidth, commentResult.width + startX);
      } else if (block.kind === "str-frag-def") {
        const fragResult = renderStrFragDefSvg(block, startX, 0);
        maxContentWidth = Math.max(maxContentWidth, fragResult.width + startX);
      } else if (block.kind === "roles-frag-def") {
        const fragResult = renderRolesFragDefSvg(block, startX, 0);
        maxContentWidth = Math.max(maxContentWidth, fragResult.width + startX);
      }
    }
    let totalWidth = maxContentWidth + 40;
    if (maxWidth && maxWidth > 0) {
      totalWidth = Math.min(totalWidth, maxWidth);
    }
    const titleWidth = totalWidth - startX - startX;
    const elements = [];
    let currentY = 20;
    let lastWasPrompt = false;
    for (const block of blocks) {
      if (block.kind === "prompt") {
        if (lastWasPrompt) {
          elements.push(svgLine(startX, currentY + 6, 200, currentY + 6, {
            stroke: COLORS.borderMedium,
            strokeWidth: 1,
            strokeDasharray: "4,4"
          }));
          currentY += 20;
        }
        const titleResult = renderPromptTitle2(block.title, startX, currentY, titleWidth);
        elements.push(titleResult.svg);
        const borderStartY = currentY + titleResult.height;
        currentY += titleResult.height + SPACING.blockGap;
        const bodyMaxWidth = titleWidth + 20;
        const bodyResult = renderPromptBody2(block.body, startX, currentY, bodyMaxWidth);
        elements.push(svgLine(startX, borderStartY, startX, currentY + bodyResult.height, {
          stroke: COLORS.borderMedium,
          strokeWidth: 1
        }));
        elements.push(bodyResult.svg);
        currentY += bodyResult.height + SPACING.blockGap;
        lastWasPrompt = true;
      } else if (block.kind === "comment-block") {
        const commentMaxWidth = titleWidth + 20;
        const commentResult = renderComment(block.text, startX, currentY, false, commentMaxWidth);
        elements.push(commentResult.svg);
        currentY += commentResult.height + SPACING.elementGap;
        lastWasPrompt = false;
      } else if (block.kind === "str-frag-def") {
        const fragResult = renderStrFragDefSvg(block, startX, currentY, titleWidth);
        elements.push(fragResult.svg);
        currentY += fragResult.height + SPACING.blockGap;
        lastWasPrompt = false;
      } else if (block.kind === "roles-frag-def") {
        const fragResult = renderRolesFragDefSvg(block, startX, currentY, titleWidth);
        elements.push(fragResult.svg);
        currentY += fragResult.height + SPACING.blockGap;
        lastWasPrompt = false;
      }
    }
    const totalHeight = currentY + 20;
    return wrapSvg(elements.join("\n"), totalWidth, totalHeight);
  }
  return __toCommonJS(standalone_entry_exports);
})();
/*! Bundled license information:

opentype.js/dist/opentype.module.js:
  (*! https://mths.be/codepointat v0.2.0 by @mathias *)
*/

